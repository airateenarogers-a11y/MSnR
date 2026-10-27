from __future__ import annotations

from datetime import datetime, timedelta
import json
from uuid import uuid4

from .clock import iso
from .config import Settings
from .domain import Quote, Signal, SymbolSpec, fingerprint
from .risk import Account, size_trade
from .store import Store, encode


class Execution:
    def __init__(self, store: Store, settings: Settings, broker=None):
        self.store = store
        self.settings = settings
        self.broker = broker

    def submit(self, signal: Signal, quote: Quote, spec: SymbolSpec, account: Account, now: datetime) -> dict:
        order_id = str(uuid4())
        with self.store.transaction() as db:
            existing = db.execute("SELECT * FROM orders WHERE signal_id=?", (signal.id,)).fetchone()
            if existing:
                return {"id": existing["id"], "status": existing["status"], "duplicate": True}
            structure_key = "executed_structure:" + fingerprint(
                signal.symbol, signal.direction, signal.structure_ids
            )
            if self.store.state(structure_key, None, db):
                return {"status": "rejected", "reasons": ["structure_already_executed_by_another_model"]}
            row = db.execute("SELECT status FROM signals WHERE id=?", (signal.id,)).fetchone()
            if not row or row["status"] != "Published":
                return {"status": "rejected", "reasons": ["signal_not_published"]}
            reserved = db.execute(
                "SELECT COALESCE(SUM(risk),0),COUNT(*) FROM orders WHERE status IN ('reserved','submitting','unknown')"
            ).fetchone()
            open_rows = db.execute("SELECT payload FROM positions WHERE status='open'").fetchall()
            local_risk = sum(json.loads(p["payload"])["risk_cash"] for p in open_rows)
            account = account.model_copy(
                update={
                    "open_risk": max(account.open_risk, local_risk),
                    "open_positions": max(account.open_positions, len(open_rows)),
                }
            )
            decision = size_trade(
                self.settings,
                signal,
                quote,
                spec,
                account,
                now,
                reserved_risk=reserved[0],
                reserved_count=reserved[1],
                killed=self.store.state("kill", False, db)
                or self.store.state("suspended", False, db)
                or self.store.state("feed_blocked", False, db),
            )
            if not decision.accepted:
                self.store.event("execution.rejected", signal.id, decision.model_dump(), now, db)
                return {"status": "rejected", "reasons": decision.reasons}
            payload = {
                "signal": signal.model_dump(mode="json"),
                "spec": spec.model_dump(),
                "decision": decision.model_dump(),
                "mode": self.settings.mode,
                "account_id": account.id,
                "risk_phase": account.risk_phase,
            }
            db.execute(
                "INSERT INTO orders VALUES(?,?,'reserved',?,?,?,?,?)",
                (order_id, signal.id, iso(now), decision.risk_cash, decision.volume, None, encode(payload)),
            )
            self.store.event("order.reserved", order_id, payload, now, db)
            self.store.set_state(structure_key, order_id, db)
        if self.settings.mode in ("paper", "backtest"):
            self._paper_open(order_id, signal, quote, spec, decision, now)
            return {"id": order_id, "status": "filled", "mode": self.settings.mode}
        if self.broker is None:
            self._status(order_id, "rejected", {"reason": "Broker not configured"}, now)
            return {"id": order_id, "status": "rejected"}
        self._status(order_id, "submitting", {}, now)
        try:
            result = self.broker.place(order_id, signal, decision, spec, account.id)
        except Exception:
            self._status(
                order_id, "unknown", {"reason": "Transport outcome unknown; reconcile before any retry"}, now
            )
            self.store.set_state("suspended", True)
            return {"id": order_id, "status": "unknown"}
        status = result.get("status", "unknown")
        if status not in ("filled", "partial", "rejected"):
            status = "unknown"
        self._status(order_id, status, result, now)
        if status in ("filled", "partial", "unknown"):
            self.store.set_state("reconciliation_complete", False)
        if status in ("partial", "unknown"):
            # Broker snapshots/deals are authoritative; freeze new execution until reconciled.
            self.store.set_state("suspended", True)
        return {"id": order_id, "status": status}

    def _status(self, order_id, status, result, now):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE orders SET status=?,broker_id=COALESCE(?,broker_id) WHERE id=?",
                (status, str(result["ticket"]) if result.get("ticket") else None, order_id),
            )
            self.store.event("order." + status, order_id, result, now, db)

    def _paper_open(self, order_id, signal, quote, spec, decision, now):
        price = (
            quote.ask if signal.direction.sign == 1 else quote.bid
        ) + signal.direction.sign * self.settings.risk.max_slippage_ticks * spec.tick_size
        payload = {
            "signal": signal.model_dump(mode="json"),
            "spec": spec.model_dump(),
            "entry": price,
            "original_volume": decision.volume,
            "remaining_volume": decision.volume,
            "stop": signal.stop,
            "partials": decision.partial_volumes,
            "next_target": 0,
            "opened_at": iso(now),
            "risk_cash": decision.risk_cash,
            "mode": self.settings.mode,
        }
        with self.store.transaction() as db:
            db.execute(
                "UPDATE orders SET status='filled',broker_id=? WHERE id=?", ("paper-" + order_id, order_id)
            )
            db.execute(
                "INSERT INTO positions VALUES(?,?,?,'open',?)",
                (order_id, order_id, signal.symbol, encode(payload)),
            )
            self.store.transition(signal.id, "Triggered", {"order_id": order_id}, now, db)
            self.store.transition(signal.id, "Active", {"order_id": order_id}, now, db)
            cost = decision.volume * self.settings.risk.commission_per_lot / 2
            self._fill(
                db,
                order_id,
                "entry",
                price,
                decision.volume,
                -cost,
                0,
                cost,
                now,
                "paper-" + order_id + "-entry",
            )

    def _fill(self, db, order_id, kind, price, volume, net, gross, cost, now, fill_id):
        payload = {
            "kind": kind,
            "price": price,
            "volume": volume,
            "net": net,
            "gross": gross,
            "cost": cost,
            "mode": self.settings.mode,
        }
        inserted = db.execute(
            "INSERT OR IGNORE INTO fills VALUES(?,?,?,?)", (fill_id, order_id, iso(now), encode(payload))
        ).rowcount
        if inserted:
            self.store.event("trade." + kind, order_id, payload, now, db)
            order = db.execute("SELECT signal_id,payload FROM orders WHERE id=?", (order_id,)).fetchone()
            signal = json.loads(order["payload"])["signal"]
            self.store.enqueue(
                "fill:" + fill_id,
                {
                    "type": "trade update",
                    "order_id": order_id,
                    "signal_id": order["signal_id"],
                    "symbol": signal["symbol"],
                    "direction": signal["direction"],
                    **payload,
                },
                now,
                db,
            )

    def mark(self, quote: Quote, now: datetime, position_id=None):
        if self.settings.mode not in ("paper", "backtest"):
            raise ValueError("Broker positions require actual deal reconciliation")
        for row in self.store.rows(
            "SELECT * FROM positions WHERE status='open' AND symbol=?", (quote.symbol,)
        ):
            if position_id is not None and row["id"] != position_id:
                continue
            with self.store.transaction() as db:
                current = db.execute(
                    "SELECT * FROM positions WHERE id=? AND status='open'", (row["id"],)
                ).fetchone()
                if not current:
                    continue
                p = json.loads(current["payload"])
                signal = Signal.model_validate(p["signal"])
                spec = SymbolSpec.model_validate(p["spec"])
                sign = signal.direction.sign
                price = quote.bid if sign == 1 else quote.ask
                hit_stop = (price - p["stop"]) * sign <= 0
                while p["remaining_volume"] > 1e-9:
                    index = p["next_target"]
                    target_hit = index < 3 and (price - signal.targets[index]) * sign >= 0
                    if not hit_stop and not target_hit:
                        break
                    volume = (
                        p["remaining_volume"]
                        if hit_stop
                        else min(p["remaining_volume"], p["partials"][index])
                    )
                    # A market stop uses observed adverse quote; limit TP does not receive favorable gap improvement.
                    exit_price = (
                        price - sign * self.settings.risk.max_slippage_ticks * spec.tick_size
                        if hit_stop
                        else signal.targets[index]
                    )
                    gross = (exit_price - p["entry"]) * sign / spec.tick_size * spec.tick_value_loss * volume
                    cost = volume * self.settings.risk.commission_per_lot / 2
                    kind = "stop" if hit_stop else f"tp{index + 1}"
                    self._fill(
                        db,
                        row["order_id"],
                        kind,
                        exit_price,
                        volume,
                        gross - cost,
                        gross,
                        cost,
                        now,
                        "paper-" + row["order_id"] + "-" + kind,
                    )
                    p["remaining_volume"] = max(0, round(p["remaining_volume"] - volume, 10))
                    if not hit_stop:
                        p["next_target"] += 1
                        if index == 0:
                            p["stop"] = p["entry"]
                            self.store.event(
                                "position.breakeven",
                                row["id"],
                                {"stop": p["stop"], "after_confirmed_tp1": True},
                                now,
                                db,
                            )
                    if hit_stop:
                        break
                closed = p["remaining_volume"] <= 1e-9
                db.execute(
                    "UPDATE positions SET status=?,payload=? WHERE id=?",
                    ("closed" if closed else "open", encode(p), row["id"]),
                )
                if closed:
                    db.execute("UPDATE orders SET status='closed' WHERE id=?", (row["order_id"],))
                    self.store.transition(
                        signal.id, "Closed", {"reason": "stop" if hit_stop else "all_targets"}, now, db
                    )
                    self.store.event(
                        "position.closed",
                        row["id"],
                        {"reason": "stop" if hit_stop else "all_targets"},
                        now,
                        db,
                    )

    def reconcile(self, now: datetime) -> dict:
        if self.broker is None:
            return {"status": "not_configured"}
        tracked = self.store.rows("SELECT * FROM orders WHERE status NOT IN ('rejected','closed')")
        # Include every unresolved/open local order, even if it is years old.
        # Untracked broker positions still appear in positions_get and block execution.
        since = min(
            [now - timedelta(days=1)] + [datetime.fromisoformat(o["created_at"]) for o in tracked]
        ) - timedelta(minutes=5)
        result = self.broker.reconcile(since=since)
        if not result.get("complete"):
            self.store.set_state("suspended", True)
            return {"status": "incomplete"}
        deals = result.get("deals", [])
        known_positions = set()
        for order in tracked:
            payload = json.loads(order["payload"])
            if payload["mode"] not in ("demo", "live"):
                continue
            prefix = "msnr:" + order["id"].replace("-", "")[:20]
            opening = [
                d
                for d in deals
                if (str(d.get("order")) == str(order["broker_id"]) or d.get("comment", "").startswith(prefix))
                and d.get("entry") == 0
            ]
            if not opening:
                continue
            ids = {int(d["position_id"]) for d in opening}
            known_positions.update(ids)
            related = [d for d in deals if int(d.get("position_id", -1)) in ids]
            snapshots = [p for p in result.get("positions", []) if int(p["ticket"]) in ids]
            signal = Signal.model_validate(payload["signal"])
            original = sum(d["volume"] for d in opening)
            entry = sum(d["price"] * d["volume"] for d in opening) / original
            remaining = sum(p["volume"] for p in snapshots)
            snapshot = snapshots[0] if len(snapshots) == 1 else None
            partials = tuple(original * x for x in (0.5, 0.3, 0.2))
            state = {
                "signal": signal.model_dump(mode="json"),
                "spec": payload["spec"],
                "entry": entry,
                "original_volume": original,
                "remaining_volume": remaining,
                "stop": snapshot["sl"] if snapshot else signal.stop,
                "partials": partials,
                "opened_at": iso(datetime.fromtimestamp(min(d["time"] for d in opening), now.tzinfo)),
                "risk_cash": order["risk"],
                "mode": payload["mode"],
                "broker_position_ids": sorted(ids),
                "next_target": 0
                if remaining > original * 0.5 + 1e-8
                else 1
                if remaining > original * 0.2 + 1e-8
                else 2,
            }
            with self.store.transaction() as db:
                old = db.execute("SELECT payload FROM positions WHERE id=?", (order["id"],)).fetchone()
                if old:
                    previous = json.loads(old["payload"])
                    if previous.get("pending_management"):
                        state["pending_management"] = previous["pending_management"]
                for d in related:
                    cost = -sum(float(d.get(k, 0)) for k in ("commission", "swap", "fee"))
                    gross = float(d.get("profit", 0))
                    at = datetime.fromtimestamp(d.get("time_msc", d["time"] * 1000) / 1000, now.tzinfo)
                    self._fill(
                        db,
                        order["id"],
                        "entry" if d.get("entry") == 0 else "broker_exit",
                        d["price"],
                        d["volume"],
                        gross - cost,
                        gross,
                        cost,
                        at,
                        "mt5-" + payload["account_id"] + "-" + str(d["ticket"]),
                    )
                current = db.execute("SELECT status FROM signals WHERE id=?", (signal.id,)).fetchone()[
                    "status"
                ]
                if current == "Published":
                    self.store.transition(signal.id, "Triggered", {"broker_fill": True}, now, db)
                    current = "Triggered"
                if current == "Triggered":
                    self.store.transition(signal.id, "Active", {"broker_fill": True}, now, db)
                closed = (
                    remaining <= 1e-8
                    and sum(d["volume"] for d in related if d.get("entry") in (1, 3)) >= original - 1e-8
                )
                db.execute(
                    "INSERT INTO positions VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload",
                    (order["id"], order["id"], signal.symbol, "closed" if closed else "open", encode(state)),
                )
                db.execute(
                    "UPDATE orders SET status=?,broker_id=? WHERE id=?",
                    (
                        "closed" if closed else "filled" if original >= order["volume"] - 1e-8 else "partial",
                        str(opening[0]["order"]),
                        order["id"],
                    ),
                )
                if closed:
                    self.store.transition(signal.id, "Closed", {"broker_deals_confirmed": True}, now, db)
        unknown_positions = [
            p for p in result.get("positions", []) if int(p.get("ticket", -1)) not in known_positions
        ]
        unresolved = self.store.rows(
            "SELECT id FROM orders WHERE status IN ('unknown','submitting','reserved','partial')"
        )
        # Unknown positions/uncertain transmission need deal-level operator review, never automatic resubmission.
        self.store.set_state("broker_snapshot", result)
        self.store.set_state("reconciliation_complete", not unknown_positions and not unresolved)
        self.store.event(
            "broker.reconciled",
            "account",
            {
                "positions": len(result.get("positions", [])),
                "unknown_positions": len(unknown_positions),
                "unresolved_intents": len(unresolved),
            },
            now,
        )
        if unknown_positions or unresolved:
            self.store.set_state("suspended", True)
            return {
                "status": "review_required",
                "unknown_positions": len(unknown_positions),
                "unresolved": len(unresolved),
            }
        return {"status": "reconciled", "positions": len(result.get("positions", []))}

    def manage_broker(self, quote: Quote, now: datetime):
        """One durable partial-close intent per target, BE only after confirmed TP1 fills."""
        from uuid import UUID, uuid5

        if self.broker is None:
            return
        for row in self.store.rows(
            "SELECT * FROM positions WHERE status='open' AND symbol=?", (quote.symbol,)
        ):
            p = json.loads(row["payload"])
            s = Signal.model_validate(p["signal"])
            spec = SymbolSpec.model_validate(p["spec"])
            ids = p.get("broker_position_ids", [])
            if len(ids) != 1:
                self.store.set_state("suspended", True)
                continue
            sign = s.direction.sign
            price = quote.bid if sign == 1 else quote.ask
            index = p["next_target"]
            # Pending intent is never blindly repeated; read broker command status and reconcile first.
            if p.get("pending_management"):
                status = self.broker.command_status(p["pending_management"]["command_id"])
                if status.get("status") in ("filled", "rejected"):
                    p.pop("pending_management", None)
                    with self.store.transaction() as db:
                        db.execute("UPDATE positions SET payload=? WHERE id=?", (encode(p), row["id"]))
                else:
                    self.store.set_state("suspended", True)
                continue
            if index >= 1 and (p["stop"] - p["entry"]) * sign < 0:
                command_id = str(uuid5(UUID(row["order_id"]), "breakeven"))

                def action():
                    return self.broker.modify(command_id, ids[0], p["entry"], s.targets[-1])

                kind = "breakeven"
            elif index < 3 and (price - s.targets[index]) * sign >= 0:
                volume = min(p["remaining_volume"], p["partials"][index])
                if (
                    volume < spec.volume_min
                    or abs(volume / spec.volume_step - round(volume / spec.volume_step)) > 1e-6
                ):
                    self.store.set_state("suspended", True)
                    self.store.event(
                        "position.management_blocked",
                        row["id"],
                        {"reason": "Partial filled volume incompatible with 50/30/20 broker steps"},
                        now,
                    )
                    continue
                command_id = str(uuid5(UUID(row["order_id"]), "tp" + str(index + 1)))

                def action():
                    return self.broker.close_position(command_id, ids[0], volume)

                kind = "tp" + str(index + 1)
            else:
                continue
            p["pending_management"] = {"command_id": command_id, "kind": kind}
            with self.store.transaction() as db:
                db.execute("UPDATE positions SET payload=? WHERE id=?", (encode(p), row["id"]))
                self.store.event("position.management_intent", row["id"], p["pending_management"], now, db)
            try:
                result = action()
            except Exception:
                result = {"status": "unknown"}
            self.store.event(
                "position.management_result", row["id"], {"command_id": command_id, **result}, now
            )
            if result.get("status") not in ("filled",):
                self.store.set_state("suspended", True)
