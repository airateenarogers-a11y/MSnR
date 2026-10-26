from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import json

from .analytics import analytics, monte_carlo, trades
from .clock import PKT, iso
from .config import Settings
from .domain import Bar, Quote, SymbolSpec
from .execution import Execution
from .risk import Account, account_controls
from .store import Store, encode
from .strategy.engine import Engine, Snapshot


def paper_account(store: Store, settings: Settings, now: datetime) -> Account:
    records = trades(store)
    base = settings.risk.paper_balance
    balance = base + sum(r["net"] for r in records)
    active = store.rows("SELECT payload FROM positions WHERE status='open'")
    unrealized = 0.0
    prices_complete = True
    for row in active:
        p = json.loads(row["payload"])
        s = p["signal"]
        raw = store.state("quote:" + s["symbol"], None)
        if (
            raw is None
            or not 0
            <= (now - datetime.fromisoformat(raw["time"])).total_seconds()
            <= settings.risk.quote_max_age_seconds
        ):
            prices_complete = False
            continue
        sign = 1 if s["direction"] == "BUY" else -1
        price = raw["bid"] if sign == 1 else raw["ask"]
        unrealized += (
            (price - p["entry"])
            * sign
            / p["spec"]["tick_size"]
            * p["spec"]["tick_value_loss"]
            * p["remaining_volume"]
        )
    store.set_state("unrealized", unrealized if prices_complete else None)
    store.set_state("valuation_at", iso(now) if prices_complete else None)
    equity = balance + unrealized
    day = now.astimezone(PKT).date()
    before = [
        f
        for f in store.rows("SELECT at,payload FROM fills")
        if datetime.fromisoformat(f["at"]).astimezone(PKT).date() < day
    ]
    day_start = base + sum(json.loads(f["payload"])["net"] for f in before)
    peak = max(base, equity, store.state("paper_high_water", base))
    store.set_state("paper_high_water", peak)
    closed = sorted(
        [
            r
            for r in records
            if r["closed_at"] and datetime.fromisoformat(r["closed_at"]).astimezone(PKT).date() == day
        ],
        key=lambda r: r["closed_at"],
        reverse=True,
    )
    losses = 0
    for r in closed:
        if r["net"] < 0:
            losses += 1
        else:
            break
    open_risk = sum(
        json.loads(r["payload"])["risk_cash"]
        * json.loads(r["payload"])["remaining_volume"]
        / json.loads(r["payload"])["original_volume"]
        for r in active
    )
    return Account(
        id="paper",
        mode="paper",
        at=now,
        balance=max(0.01, balance),
        equity=max(0.01, equity),
        free_margin=max(0, equity),
        day_start_equity=max(0.01, day_start),
        high_water_equity=max(0.01, peak),
        open_risk=open_risk,
        open_positions=len(active),
        consecutive_daily_losses=losses,
        trading_allowed=equity > 0,
        reconciled=prices_complete,
        **account_controls(store, settings, records, now, equity, base, peak, "paper"),
    )


def replay(
    settings: Settings,
    datasets: dict[str, dict[str, list[Bar]]],
    specs: dict[str, SymbolSpec],
    destination: Path,
    spread: dict[str, float],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    evaluator=None,
) -> dict:
    if destination.exists():
        raise ValueError(
            "Backtest database must be new to prevent results from prior runs contaminating this run"
        )
    settings = settings.model_copy(update={"mode": "backtest"})
    store = Store(destination)
    engine = evaluator or Engine(settings)
    execution = Execution(store, settings)
    clock = sorted(
        {
            b.time
            for by_tf in datasets.values()
            for b in by_tf.get("M1", [])
            if (start is None or b.time >= start) and (end is None or b.time < end)
        }
    )
    if not clock:
        raise ValueError("Replay requires chronological M1 execution bars")
    rejections = Counter()
    evaluations = 0
    for time in clock:
        for symbol, frames in datasets.items():
            execution_bars = [b for b in frames.get("M1", []) if b.time == time]
            if not execution_bars:
                continue
            b = execution_bars[0]
            s = specs[symbol]
            spread_price = spread[symbol]
            if spread_price < 0:
                raise ValueError("Negative spread")
            bid = b.open
            q = Quote(symbol=symbol, time=time, bid=bid, ask=bid + spread_price)
            store.set_state("quote:" + symbol, q.model_dump(mode="json"))
            # Only data closed at the new bar open is observable; no use of this bar's high/low to enter.
            visible = {tf: [x for x in bs if x.end <= time] for tf, bs in frames.items()}
            visible = {tf: bs for tf, bs in visible.items() if bs}
            peers = {
                p: {tf: [x for x in bs if x.end <= time] for tf, bs in tfs.items()}
                for p, tfs in datasets.items()
                if p != symbol
            }
            result = engine.evaluate(Snapshot(time, symbol, visible, s, q, peers, specs))
            evaluations += 1
            for item in result.rejected:
                rejections[item.get("reason") or "|".join(item.get("rules", []))] += 1
            for signal in result.signals:
                if store.add_signal(signal):
                    store.transition(signal.id, "Published", {"channel": "historical_replay"}, time)
                    execution.submit(signal, q, s, paper_account(store, settings, time), time)
            # Worst-case path for ambiguous OHLC bars: adverse extreme before favorable extreme, per position.
            for row in store.rows("SELECT * FROM positions WHERE status='open' AND symbol=?", (symbol,)):
                position = json.loads(row["payload"])
                direction = position["signal"]["direction"]
                adverse = b.low if direction == "BUY" else b.high
                favorable = b.high if direction == "BUY" else b.low
                # mark all positions using the same pessimistic path; do not use a favorable high first.
                execution.mark(
                    Quote(symbol=symbol, time=b.end, bid=adverse, ask=adverse + spread_price),
                    b.end,
                    row["id"],
                )
                execution.mark(
                    Quote(symbol=symbol, time=b.end, bid=favorable, ask=favorable + spread_price),
                    b.end,
                    row["id"],
                )
    result = analytics(store, settings.risk.paper_balance)
    closed = trades(store)
    benchmarks = {
        symbol: {
            "buy_and_hold_price_return": frames["M1"][-1].close / frames["M1"][0].open - 1,
            "description": "Unlevered gross price return; not risk-equivalent to strategy, excludes financing",
        }
        for symbol, frames in datasets.items()
        if frames.get("M1")
    }
    result.update(
        {
            "run_id": str(uuid4()),
            "policy_hash": settings.policy.digest,
            "evaluations": evaluations,
            "rejections": dict(rejections),
            "data_sources": sorted({b.source for f in datasets.values() for bs in f.values() for b in bs}),
            "monte_carlo": monte_carlo([r["realized_r"] for r in closed if r["realized_r"] is not None]),
            "benchmarks": benchmarks,
            "status": "completed"
            if result["closed_trades"]
            else "no_completed_trades_not_strategy_validation",
            "assumptions": {
                "intrabar_path": "stop first, adverse open on gaps",
                "spread": spread,
                "commission_per_lot_round_trip": settings.risk.commission_per_lot,
                "slippage_ticks": settings.risk.max_slippage_ticks,
                "close_at_end": False,
            },
            "limitations": [
                "Bar replay cannot reproduce tick ordering or prove a live trading edge.",
                "Open trades at dataset end remain open; they are not fabricated exits.",
            ],
        }
    )
    with store.transaction() as db:
        db.execute(
            "INSERT INTO research VALUES(?,?,?,?,?)",
            (result["run_id"], iso(clock[-1]), "backtest", settings.policy.digest, encode(result)),
        )
    return result


def walk_forward_windows(times: list[datetime], train: int, test: int, embargo: int = 1):
    if train < 2 or test < 1 or embargo < 0 or times != sorted(set(times)):
        raise ValueError("Unique chronological times and valid split lengths required")
    windows = []
    for i in range(train + embargo, len(times) - test + 1, test):
        windows.append(
            {
                "train": (times[i - embargo - train], times[i - embargo - 1]),
                "test": (times[i], times[i + test - 1]),
                "embargo_bars": embargo,
            }
        )
    return windows
