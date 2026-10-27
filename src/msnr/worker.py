from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import signal as os_signal
import socket
import threading
from uuid import uuid4

from .backtest import paper_account
from .charts import render
from .clock import iso, utcnow
from .config import Settings, RiskLimits
from .data import TIMEFRAMES
from .domain import Signal
from .execution import Execution
from .risk import Account, account_controls
from .integrations.discord import Discord, signal_embed
from .integrations.mt5 import MT5Bridge
from .reports import schedule_reports
from .store import Store
from .strategy.engine import Engine, Snapshot
from .process_identity import identity
from .market_health import MarketDataUnavailable

log = logging.getLogger("msnr")


class LeaseUnavailable(RuntimeError):
    pass


class WorkerStopping(Exception):
    pass


class Worker:
    def __init__(self, store: Store, settings: Settings, bridge=None):
        self.store = store
        self.settings = settings
        self.base_settings = settings
        self.engine = Engine(settings)
        self.bridge = bridge
        if bridge is None and os.getenv("MSNR_BRIDGE_URL"):
            self.bridge = MT5Bridge()
        self.execution = Execution(store, settings, self.bridge)
        self.discord = (
            Discord(store, os.environ["MSNR_DISCORD_WEBHOOK"]) if os.getenv("MSNR_DISCORD_WEBHOOK") else None
        )
        self.owner = str(uuid4())
        self.process_id = os.getpid()
        self.process_identity = identity(self.process_id)
        self.session = os.getenv("MSNR_WORKER_SESSION")
        self.host = socket.gethostname()
        self.stop_event = threading.Event()
        self.recovered = False

    def lease(self, now):
        with self.store.transaction() as db:
            old = self.store.state("worker_lease", None, db)
            if old and old["owner"] != self.owner and datetime.fromisoformat(old["until"]) > now:
                ended = False
                if old.get("host") == self.host and old.get("process_identity") and old.get("pid"):
                    try:
                        ended = identity(old["pid"]) != old["process_identity"]
                    except (OSError, ValueError):
                        pass
                if not ended:
                    raise LeaseUnavailable("Another worker holds the database lease until " + old["until"])
                self.store.event(
                    "worker.lease_recovered",
                    self.owner,
                    {"previous_owner": old["owner"], "reason": "Prior local process has ended"},
                    now,
                    db,
                )
            self.store.set_state(
                "worker_lease",
                {
                    "owner": self.owner,
                    "until": iso(now + timedelta(minutes=10)),
                    "pid": self.process_id,
                    "process_identity": self.process_identity,
                    "host": self.host,
                    "session": self.session,
                },
                db,
            )

    def stop_requested(self):
        stop_file = os.getenv("MSNR_WORKER_STOP_FILE")
        return self.stop_event.is_set() or bool(stop_file and Path(stop_file).is_file())

    def _bars(self, symbol, initial=None):
        bars = dict(initial or {})
        for timeframe in TIMEFRAMES:
            if timeframe in bars:
                continue
            if self.stop_requested():
                raise WorkerStopping()
            now = utcnow()
            self.lease(now)
            self.store.set_state(
                "worker_health",
                {
                    "at": iso(now),
                    "status": "loading_market_data",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "mode": self.settings.mode,
                },
            )
            bars[timeframe] = self.bridge.bars(symbol, timeframe, 500)
        return bars

    def feed_failure(self, exc):
        now = utcnow()
        incident = self.store.state("feed_incident")
        first = not incident or not incident.get("active")
        if first:
            incident = {"id": str(uuid4()), "started_at": iso(now), "attempts": 0}
        incident.update(
            active=True,
            recovered_checks=0,
            at=iso(now),
            details=exc.details,
            attempts=incident["attempts"] + 1,
        )
        delay = min(60, max(5, exc.details["retry_after"]) * 2 ** min(incident["attempts"] - 1, 3))
        incident["retry_at"] = iso(now + timedelta(seconds=delay))
        self.store.set_state("feed_incident", incident)
        self.store.set_state("feed_blocked", True)
        self.store.set_state(
            "worker_health",
            {
                "at": iso(now),
                "status": "waiting_for_mt5",
                "reason": str(exc),
                "retry_at": incident["retry_at"],
                "details": exc.details,
            },
        )
        log.warning(
            json.dumps({"event": "worker.feed_wait", **exc.details, "retry_at": incident["retry_at"]})
        )
        if first:
            self.store.event("feed.interrupted", incident["id"], exc.details, now)
            last = self.store.state("feed_notice_at")
            if not last or now - datetime.fromisoformat(last) >= timedelta(minutes=15):
                self.store.enqueue(
                    "feed:" + incident["id"],
                    {
                        "type": "market feed delayed",
                        "summary": f"{exc}. New entries wait for fresh data. Automatic retry is active; use Check MT5 for details.",
                    },
                    now,
                )
                self.store.set_state("feed_notice_at", iso(now))
        self.deliver_notice(now)

    def deliver_notice(self, now):
        if self.discord and self.store.state("notifications_enabled", True):
            self.discord.deliver_one(now)

    def once(self):
        self.lease(utcnow())
        incident = self.store.state("feed_incident")
        if incident and incident.get("active") and utcnow() < datetime.fromisoformat(incident["retry_at"]):
            self.deliver_notice(utcnow())
            return
        try:
            self._once()
        except MarketDataUnavailable as exc:
            self.feed_failure(exc)

    def _once(self):
        now = utcnow()
        self.lease(now)
        if not self.recovered:
            if self.discord:
                self.discord.recover()
            with self.store.transaction() as db:
                cancelled = db.execute(
                    "UPDATE outbox SET status='cancelled',error='Superseded by consolidated feed diagnostics' "
                    "WHERE status='pending' AND event_key LIKE 'failure:%'"
                ).rowcount
                if cancelled:
                    self.store.event(
                        "notification.legacy_failures_superseded", "worker", {"count": cancelled}, db=db
                    )
            self.recovered = True
        self.settings = self.base_settings
        runtime_risk = self.store.state("runtime_risk", None)
        if runtime_risk:
            self.settings = self.settings.model_copy(update={"risk": RiskLimits.model_validate(runtime_risk)})
            self.execution.settings = self.settings
            self.engine.settings = self.settings
        selected = self.store.state("runtime_instruments", None)
        if selected is not None:
            self.settings = self.settings.model_copy(
                update={
                    "instruments": tuple(
                        i.model_copy(update={"enabled": i.symbol in selected})
                        for i in self.settings.instruments
                    )
                }
            )
            self.engine.settings = self.settings
            self.execution.settings = self.settings
        if self.bridge is None:
            self.store.set_state(
                "worker_health",
                {
                    "at": iso(now),
                    "status": "waiting_for_market_data",
                    "reason": "MT5 Windows bridge is not configured",
                },
            )
            return
        self.store.set_state(
            "worker_health",
            {
                "at": iso(now),
                "status": "checking_mt5",
                "reason": "Checking MT5 account and reconciliation",
            },
        )
        account = self.bridge.account()
        self.store.set_state("account_snapshot", account)
        if self.settings.mode in ("demo", "live"):
            reconciliation = self.execution.reconcile(now)
            if reconciliation["status"] != "reconciled":
                self.store.set_state("suspended", True)
        symbol_list = {s["symbol"] for s in self.bridge.symbols()}
        self.store.set_state("feed_blocked", False)
        statuses = {}
        resolved = []
        names = {}
        for instrument in self.settings.instruments:
            matches = [s for s in instrument.aliases if s in symbol_list]
            actual = (
                instrument.symbol
                if instrument.symbol in symbol_list
                else matches[0]
                if len(matches) == 1
                else instrument.symbol
            )
            if actual in names:
                raise ValueError("Two configured instruments resolve to the same broker symbol")
            names[actual] = instrument.symbol
            resolved.append(instrument.model_copy(update={"symbol": actual}))
        self.settings = self.settings.model_copy(update={"instruments": tuple(resolved)})
        self.engine.settings = self.settings
        self.execution.settings = self.settings
        self.store.set_state("broker_symbols", {original: actual for actual, original in names.items()})
        for instrument in self.settings.instruments:
            if self.stop_requested():
                return
            self.lease(utcnow())
            has_positions = bool(
                self.store.rows(
                    "SELECT id FROM positions WHERE status='open' AND symbol=?", (instrument.symbol,)
                )
            )
            if not instrument.enabled and not has_positions:
                continue
            configured = [s for s in (instrument.symbol, *instrument.aliases) if s in symbol_list]
            if not configured:
                statuses[instrument.symbol] = {
                    "status": "unavailable",
                    "reason": "Exact broker symbol and explicit aliases not found",
                }
                continue
            selected = configured[0]
            if selected != instrument.symbol:
                statuses[instrument.symbol] = {
                    "status": "alias_requires_config_update",
                    "broker_symbol": selected,
                }
                continue
            try:
                quote = self.bridge.quote(selected)
                spec = self.bridge.spec(selected)
                self.store.set_state("spec:" + selected, spec.model_dump())
                self.store.set_state("quote:" + selected, quote.model_dump(mode="json"))
                if not spec.market_open:
                    statuses[selected] = {"status": "market_closed_or_stale"}
                    continue
                self._monitor(quote, now)
                if not instrument.enabled:
                    statuses[selected] = {"status": "managing_existing_positions_only"}
                    continue
                risk_account = (
                    paper_account(self.store, self.settings, now)
                    if self.settings.mode == "paper"
                    else self._broker_account(self.bridge.account(), now)
                )
                if (
                    risk_account.reality_check_required
                    or risk_account.cooldown_until
                    and now < risk_account.cooldown_until
                ):
                    statuses[selected] = {
                        "status": "reality_check_required"
                        if risk_account.reality_check_required
                        else "cooldown"
                    }
                    continue
                self.store.set_state(
                    "worker_health",
                    {
                        "at": iso(utcnow()),
                        "status": "loading_market_data",
                        "symbol": selected,
                        "timeframe": "M1",
                    },
                )
                m1 = self.bridge.bars(selected, "M1", 500)
                closed = [b for b in m1 if b.end <= now]
                if not closed:
                    statuses[selected] = {"status": "missing_data"}
                    continue
                checkpoint = "bar:" + selected
                if self.store.state(checkpoint) == iso(closed[-1].end):
                    statuses[selected] = {"status": "watching", "last_bar": iso(closed[-1].end)}
                    continue
                bars = self._bars(selected, {"M1": m1})
                peers = {}
                peer_specs = {}
                for peer in instrument.peer:
                    if peer in symbol_list:
                        try:
                            peer_specs[peer] = self.bridge.spec(peer)
                            peers[peer] = self._bars(peer)
                        except MarketDataUnavailable as exc:
                            if exc.details["scope"] != "symbol":
                                raise
                            # Core MSNR is standalone. SMT-required models remain
                            # rejected by the engine when peer data is unavailable.
                            peer_specs.pop(peer, None)
                            self.store.set_state("peer_status:" + selected, exc.details)
                        break
                quote = self.bridge.quote(selected)
                now = utcnow()
                self.store.set_state("quote:" + selected, quote.model_dump(mode="json"))
                partial = {}
                for tf in ("W1", "MN1"):
                    if bars[tf] and bars[tf][-1].time < now < bars[tf][-1].end:
                        # Copy rates read at this observation, not a historical finalized HTF candle.
                        partial[tf] = bars[tf][-1].model_copy(update={"end": now})
                evaluation = self.engine.evaluate(
                    Snapshot(now, selected, bars, spec, quote, peers, peer_specs, partial)
                )
                self.store.set_state(
                    "evaluation:" + selected,
                    {
                        "at": iso(now),
                        "rejected": evaluation.rejected[:100],
                        "structures": evaluation.structures,
                        "signals": len(evaluation.signals),
                    },
                )
                for s in evaluation.signals:
                    if self.stop_requested():
                        return
                    if not self.store.add_signal(s):
                        continue
                    chart = render(s, [b for b in bars[s.timeframe] if b.end <= now], Path("var/charts"))
                    with self.store.transaction() as db:
                        db.execute("UPDATE signals SET chart_path=? WHERE id=?", (str(chart), s.id))
                        self.store.transition(
                            s.id, "Published", {"channel": "dashboard", "chart": str(chart)}, now, db
                        )
                        self.store.enqueue(
                            "signal:" + s.id,
                            {"type": "signal", "body": signal_embed(s), "chart": str(chart)},
                            now,
                            db,
                        )
                    if self.settings.mode == "paper":
                        fresh_quote = self.bridge.quote(selected)
                        trade_time = utcnow()
                        self.store.set_state("quote:" + selected, fresh_quote.model_dump(mode="json"))
                        if self.stop_requested():
                            return
                        self.execution.submit(
                            s,
                            fresh_quote,
                            spec,
                            paper_account(self.store, self.settings, trade_time),
                            trade_time,
                        )
                    else:
                        fresh_quote = self.bridge.quote(selected)
                        fresh_spec = self.bridge.spec(selected)
                        fresh_account = self.bridge.account()
                        trade_time = utcnow()
                        if self.stop_requested():
                            return
                        self.execution.submit(
                            s,
                            fresh_quote,
                            fresh_spec,
                            self._broker_account(fresh_account, trade_time),
                            trade_time,
                        )
                self.store.set_state(checkpoint, iso(closed[-1].end))
                statuses[selected] = {
                    "status": "watching",
                    "last_bar": iso(closed[-1].end),
                    "signals": len(evaluation.signals),
                }
            except WorkerStopping:
                return
            except MarketDataUnavailable as exc:
                statuses[selected] = {"status": "waiting_for_data", "reason": str(exc), **exc.details}
                self.store.set_state(
                    "instrument_status",
                    {names.get(k, k): {**v, "broker_symbol": k} for k, v in statuses.items()},
                )
                if exc.details["scope"] != "symbol":
                    raise
            except Exception as exc:
                statuses[selected] = {"status": "error", "error_type": type(exc).__name__}
                self.store.set_state("suspended", True)
                self.store.event("worker.error", selected, {"error_type": type(exc).__name__}, now)
                self.store.enqueue(
                    "critical-failure:" + now.strftime("%Y-%m-%dT%H"),
                    {
                        "type": "operational failure",
                        "summary": f"{selected}: {type(exc).__name__}. New execution is suspended; inspect local diagnostics.",
                    },
                    now,
                )
        self.store.set_state(
            "instrument_status", {names.get(k, k): {**v, "broker_symbol": k} for k, v in statuses.items()}
        )
        incident = self.store.state("feed_incident")
        if incident and incident.get("active"):
            incident["recovered_checks"] = incident.get("recovered_checks", 0) + 1
            if incident["recovered_checks"] >= 2:
                incident["active"] = False
                self.store.event("feed.restored", incident["id"], {}, utcnow())
            self.store.set_state("feed_incident", incident)
        state = (
            "running"
            if any(v["status"] == "watching" for v in statuses.values())
            else (
                "waiting_for_data"
                if any(
                    v["status"] in ("waiting_for_data", "missing_data", "error") for v in statuses.values()
                )
                else "connected_no_open_markets"
            )
        )
        self.store.set_state(
            "worker_health", {"at": iso(utcnow()), "status": state, "mode": self.settings.mode}
        )
        if self.stop_requested():
            return
        schedule_reports(self.store, now, self.settings.risk.paper_balance)
        self.deliver_notice(now)

    def _monitor(self, quote, now):
        if self.settings.mode == "paper":
            self.execution.mark(quote, now)
        elif self.settings.mode in ("demo", "live"):
            self.execution.manage_broker(quote, now)
        for row in self.store.rows(
            "SELECT * FROM signals WHERE symbol=? AND status IN ('Published','Triggered')", (quote.symbol,)
        ):
            if self.store.rows("SELECT id FROM orders WHERE signal_id=?", (row["id"],)):
                continue
            s = Signal.model_validate_json(row["payload"])
            sign = s.direction.sign
            price = quote.bid if sign == 1 else quote.ask
            if row["status"] == "Published" and now >= s.expires_at:
                self.store.transition(s.id, "Expired", {"reason": "Signal deadline passed"}, now)
                continue
            if row["status"] == "Published" and (price - s.stop) * sign <= 0:
                self.store.transition(s.id, "Invalidated", {"reason": "Price passed stop before entry"}, now)
            elif row["status"] == "Published" and (price - s.entry) * sign <= 0:
                self.store.transition(s.id, "Triggered", {"executed": False, "price": price}, now)
            elif row["status"] == "Triggered" and (
                (price - s.stop) * sign <= 0 or (price - s.targets[-1]) * sign >= 0
            ):
                self.store.transition(
                    s.id,
                    "Closed",
                    {
                        "executed": False,
                        "observed_price": price,
                        "outcome": "stop" if (price - s.stop) * sign <= 0 else "final_target",
                        "hypothetical": True,
                    },
                    now,
                )

    def _broker_account(self, raw, now):
        from .clock import PKT
        from .analytics import trades

        key = "account_baseline:" + raw["id"]
        baseline = self.store.state(key, None)
        if baseline is None:
            baseline = {"equity": raw["equity"], "at": iso(now)}
            self.store.set_state(key, baseline)
            self.store.event("account.baseline", raw["id"], baseline, now)
        day_key = key + ":" + str(now.astimezone(PKT).date())
        day_equity = self.store.state(day_key, None)
        if day_equity is None:
            day_equity = raw["equity"]
            self.store.set_state(day_key, day_equity)
        peak = max(raw["equity"], self.store.state(key + ":peak", baseline["equity"]))
        self.store.set_state(key + ":peak", peak)
        positions = self.store.rows("SELECT payload FROM positions WHERE status='open'")
        open_risk = sum(json.loads(p["payload"])["risk_cash"] for p in positions)
        today = now.astimezone(PKT).date()
        closed = sorted(
            [
                r
                for r in trades(self.store)
                if r["closed_at"] and datetime.fromisoformat(r["closed_at"]).astimezone(PKT).date() == today
            ],
            key=lambda r: r["closed_at"],
            reverse=True,
        )
        losses = 0
        for r in closed:
            if r["net"] >= 0:
                break
            losses += 1
        return Account(
            id=raw["id"],
            mode=raw["mode"],
            at=datetime.fromisoformat(raw["at"]),
            balance=raw["balance"],
            equity=raw["equity"],
            free_margin=raw["free_margin"],
            day_start_equity=day_equity,
            high_water_equity=peak,
            open_risk=open_risk,
            open_positions=len(positions),
            consecutive_daily_losses=losses,
            trading_allowed=raw["trading_allowed"],
            reconciled=self.store.state("reconciliation_complete", False),
            **account_controls(
                self.store,
                self.settings,
                trades(self.store),
                now,
                raw["equity"],
                baseline["equity"],
                peak,
                raw["id"],
            ),
        )

    def run(self):
        signals = [os_signal.SIGTERM, os_signal.SIGINT]
        if hasattr(os_signal, "SIGBREAK"):
            signals.append(os_signal.SIGBREAK)
        for sig in signals:
            os_signal.signal(sig, lambda *_: self.stop_event.set())
        while not self.stop_requested():
            try:
                self.once()
            except LeaseUnavailable as exc:
                log.error(
                    json.dumps(
                        {
                            "event": "worker.lease_unavailable",
                            "reason": str(exc),
                            "action": "exit_without_mutation",
                        }
                    )
                )
                break
            except Exception as exc:
                log.error(json.dumps({"event": "worker.error", "type": type(exc).__name__}))
                try:
                    self.store.set_state("suspended", True)
                    self.store.set_state(
                        "worker_health",
                        {"at": iso(utcnow()), "status": "error", "error_type": type(exc).__name__},
                    )
                except Exception:
                    log.error('{"event":"database.unavailable","execution":"stopped"}')
            self.stop_event.wait(self.settings.worker_interval_seconds)
        self.close()

    def close(self):
        with self.store.transaction() as db:
            old = self.store.state("worker_lease", None, db)
            if old and old["owner"] == self.owner:
                self.store.set_state("worker_lease", None, db)
                self.store.set_state(
                    "worker_health",
                    {
                        "at": iso(utcnow()),
                        "status": "stopped",
                        "reason": "Worker stopped; no new setups evaluated",
                    },
                    db,
                )
        if self.bridge:
            self.bridge.close()
