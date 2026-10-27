from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import json

from pydantic import Field

from .clock import aware
from .config import Settings
from .domain import Model, Quote, Signal, SymbolSpec
from .strategy.catalog import catalog, requirements, RATING_ORDER


class Account(Model):
    id: str
    mode: str
    at: datetime
    balance: float = Field(gt=0)
    equity: float = Field(gt=0)
    free_margin: float = Field(ge=0)
    day_start_equity: float = Field(gt=0)
    high_water_equity: float = Field(gt=0)
    open_risk: float = Field(ge=0)
    open_positions: int = Field(ge=0)
    consecutive_daily_losses: int = Field(ge=0)
    trading_allowed: bool
    reconciled: bool
    cooldown_until: datetime | None = None
    reality_check_required: bool = False
    risk_phase: int = Field(default=1, ge=1, le=3)


class RiskDecision(Model):
    accepted: bool
    reasons: tuple[str, ...]
    volume: float = 0
    risk_cash: float = 0
    risk_per_lot: float = 0
    partial_volumes: tuple[float, ...] = ()


def live_permitted(settings: Settings, account: Account, now: datetime) -> bool:
    if settings.mode != "live":
        return True
    if not settings.live_authorization_file:
        return False
    try:
        data = json.loads(Path(settings.live_authorization_file).read_text())
        return (
            data["account_id"] == account.id
            and data["policy_hash"] == settings.policy.digest
            and data["explicit_authorization"] is True
            and data["demo_validated"] is True
            and data["historical_validated"] is True
            and bool(data["approved_by"])
            and aware(datetime.fromisoformat(data["expires_at"])) > now
            and aware(datetime.fromisoformat(data["authorized_at"])) <= now
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def size_trade(
    settings: Settings,
    signal: Signal,
    quote: Quote,
    spec: SymbolSpec,
    account: Account,
    now: datetime,
    *,
    reserved_risk=0.0,
    reserved_count=0,
    killed=False,
) -> RiskDecision:
    reasons = []
    limits = settings.risk
    instrument = settings.instrument(signal.symbol)
    if killed:
        reasons.append("kill_switch_or_suspension")
    if signal.policy_hash != settings.policy.digest:
        reasons.append("strategy_policy_changed")
    if signal.expires_at <= now or signal.created_at > now:
        reasons.append("signal_expired_or_future")
    if any(e.outcome != "PASS" for e in signal.evidence):
        reasons.append("unverified_strategy")
    model = next((m for m in catalog(settings.policy.version) if m.name == signal.setup), None)
    if model is None or not set(requirements(model, settings.policy.version) if model else ()) <= {
        e.rule for e in signal.evidence if e.outcome == "PASS"
    }:
        reasons.append("mandatory_strategy_evidence_missing")
    if RATING_ORDER[signal.rating] < RATING_ORDER[settings.policy.minimum_rating]:
        reasons.append("rating_below_eligibility_threshold")
    if quote.symbol != signal.symbol or spec.symbol != signal.symbol:
        reasons.append("symbol_mismatch")
    if not 0 <= (now - quote.time).total_seconds() <= limits.quote_max_age_seconds:
        reasons.append("stale_quote")
    if not 0 <= (now - aware(account.at)).total_seconds() <= limits.quote_max_age_seconds:
        reasons.append("stale_account")
    if not account.reconciled:
        reasons.append("unreconciled_account")
    if not spec.market_open or not spec.trade_allowed or not account.trading_allowed:
        reasons.append("trading_unavailable")
    if settings.mode == "demo" and account.mode != "demo":
        reasons.append("demo_account_required")
    if settings.mode == "live" and account.mode != "real":
        reasons.append("real_account_required")
    if not live_permitted(settings, account, now):
        reasons.append("live_not_authorized")
    if quote.ask - quote.bid > instrument.max_spread:
        reasons.append("spread_limit")
    if account.equity <= account.day_start_equity * (1 - limits.daily_loss):
        reasons.append("daily_loss_limit")
    if account.equity <= account.high_water_equity * (1 - limits.max_drawdown):
        reasons.append("drawdown_limit")
    if account.consecutive_daily_losses >= 3:
        reasons.append("three_consecutive_daily_losses")
    if account.cooldown_until and now < aware(account.cooldown_until):
        reasons.append("cooldown")
    if account.reality_check_required:
        reasons.append("manual_reality_check_required")
    if account.open_positions + reserved_count >= limits.max_positions:
        reasons.append("position_limit")
    price = quote.ask if signal.direction.sign == 1 else quote.bid
    slippage = limits.max_slippage_ticks * spec.tick_size
    if abs(price - signal.entry) > slippage + spec.tick_size * 1e-6:
        reasons.append("entry_moved_beyond_slippage")
    if (price - signal.stop) * signal.direction.sign <= 0 or any(
        (t - price) * signal.direction.sign <= 0 for t in signal.targets
    ):
        reasons.append("invalid_order_geometry")
    elif (
        settings.policy.version == "v5"
        and not 2 <= abs(signal.targets[0] - price) / abs(price - signal.stop) <= 3
    ):
        reasons.append("tp1_reward_risk_outside_v5_range")
    stop_reference = quote.bid if signal.direction.sign == 1 else quote.ask
    if abs(stop_reference - signal.stop) < spec.stops_distance or any(
        abs(t - stop_reference) < spec.stops_distance for t in signal.targets
    ):
        reasons.append("broker_stop_distance")
    if not spec.filling_modes:
        reasons.append("unsupported_fill_mode")
    for level in (signal.stop, *signal.targets):
        ticks = level / spec.tick_size
        if abs(ticks - round(ticks)) > 1e-5:
            reasons.append("off_tick_price")
    per_lot = (
        abs(price - signal.stop) + slippage
    ) / spec.tick_size * spec.tick_value_loss + limits.commission_per_lot
    fraction = min({1: 0.0033, 2: 0.005, 3: 0.01}[account.risk_phase], limits.per_trade)
    if settings.policy.version == "v5":
        if not limits.evaluation_mode:
            fraction = min(fraction, 0.005)
        elif account.risk_phase == 2 and account.equity <= account.high_water_equity * 0.97:
            fraction *= 0.5
    risk_cash = min(account.balance, account.equity) * fraction
    remaining = account.equity * limits.concurrent_risk - account.open_risk - reserved_risk
    risk_cash = min(risk_cash, max(0, remaining))
    raw = min(spec.volume_max, risk_cash / per_lot) if per_lot > 0 else 0
    # Multiples of 10 steps permit exact original-volume 50/30/20 management.
    unit = Decimal(str(spec.volume_step)) * 10
    volume = float((Decimal(str(raw)) / unit).to_integral_value(rounding=ROUND_FLOOR) * unit)
    partials = tuple(float(Decimal(str(volume)) * Decimal(str(p))) for p in (0.5, 0.3, 0.2))
    if volume < spec.volume_min or any(v < spec.volume_min for v in partials):
        reasons.append("insufficient_risk_for_broker_lot_partials")
    if account.free_margin <= 0:
        reasons.append("no_free_margin")
    if reasons:
        return RiskDecision(accepted=False, reasons=tuple(dict.fromkeys(reasons)))
    return RiskDecision(
        accepted=True,
        reasons=(),
        volume=volume,
        risk_cash=volume * per_lot,
        risk_per_lot=per_lot,
        partial_volumes=partials,
    )


def phase_for(equity, initial, peak, phase2_wins, policy, previous=1, *, limits=None, phase1_wins=0):
    if equity <= peak * 0.95:
        return 1
    gain = equity / initial - 1
    if policy.version == "v5":
        if limits is None or not limits.evaluation_mode:
            return 2 if equity >= initial * 1.02 and equity >= peak else 1
        if equity >= initial * 1.05 or equity >= initial * (1 + limits.evaluation_target_fraction - 0.02):
            return 3
        if previous == 3:
            return 3
        if previous == 2 or equity >= initial * 1.02 or phase1_wins >= 3:
            return 2
        return 1
    if (
        gain >= policy.prop_target_fraction - policy.phase3_target_distance
        or previous == 2
        and phase2_wins >= 3
    ):
        return 3
    if previous == 3 and gain > 0:
        return 3
    return 2 if gain >= 0.03 else 1


def account_controls(store, settings, records, now, equity, initial, peak, account_id):
    completed = sorted(
        [r for r in records if r["closed_at"] and r.get("account_id", account_id) == account_id],
        key=lambda r: r["closed_at"],
    )
    cooldown = None
    if completed:
        cooldown = datetime.fromisoformat(completed[-1]["closed_at"]) + timedelta(
            minutes=settings.policy.cooldown_minutes
        )
    confirmed = store.state("reality_confirmed_at", None)
    confirmed_at = datetime.fromisoformat(confirmed) if confirmed else None
    big = [
        r
        for r in completed
        if r["realized_r"] is not None
        and r["realized_r"] >= (settings.policy.big_win_r or 3)
        and (confirmed_at is None or datetime.fromisoformat(r["closed_at"]) > confirmed_at)
    ]
    required = bool(big)
    store.set_state("reality_required", required)
    key = "risk_phase:" + account_id
    previous = store.state(key, 1)
    wins = 0
    for r in reversed(completed):
        if r.get("risk_phase") != 2 or r["net"] <= 0:
            break
        wins += 1
    phase1_wins = 0
    for r in reversed(completed):
        if r.get("risk_phase") != 1 or r["net"] <= 0:
            break
        phase1_wins += 1
    phase = phase_for(
        equity, initial, peak, wins, settings.policy, previous, limits=settings.risk, phase1_wins=phase1_wins
    )
    if phase != previous:
        store.event("risk.phase_changed", account_id, {"from": previous, "to": phase}, now)
        store.set_state(key, phase)
    return {"cooldown_until": cooldown, "reality_check_required": required, "risk_phase": phase}
