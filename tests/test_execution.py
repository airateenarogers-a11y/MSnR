from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import sqlite3

import pytest

from msnr.domain import Quote
from msnr.execution import Execution
from msnr.risk import size_trade
from msnr.analytics import trades, analytics
from msnr.store import Store
from conftest import NOW


def publish(store, signal):
    store.add_signal(signal)
    store.transition(signal.id, "Published", {"channel": "test"}, NOW)


def test_fingerprint_persists_after_invalidation(store, signal):
    assert store.add_signal(signal)
    store.transition(signal.id, "Invalidated", {"reason": "test"}, NOW)
    assert not Store(store.path).add_signal(signal)


def test_append_only_audit_and_backup(store, tmp_path):
    store.event("test", "one", {"n": 1}, NOW)
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM events")
    store.backup(tmp_path / "copy.db")
    assert Store(tmp_path / "copy.db").verify_chain()


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"open_positions": 3}, "position_limit"),
        ({"equity": 97000}, "daily_loss_limit"),
        ({"consecutive_daily_losses": 3}, "three_consecutive_daily_losses"),
        ({"reconciled": False}, "unreconciled_account"),
        ({"at": NOW - timedelta(minutes=1)}, "stale_account"),
    ],
)
def test_risk_safety(settings, signal, quote, spec, account, change, reason):
    r = size_trade(settings, signal, quote, spec, account.model_copy(update=change), NOW)
    assert not r.accepted and reason in r.reasons


def test_spread_expansion(settings, signal, quote, spec, account):
    r = size_trade(settings, signal, quote.model_copy(update={"ask": 102}), spec, account, NOW)
    assert not r.accepted and "spread_limit" in r.reasons


def test_round_down_never_exceeds_risk(settings, signal, quote, spec, account):
    r = size_trade(settings, signal, quote, spec, account, NOW)
    assert r.accepted and r.risk_cash <= 330 and sum(r.partial_volumes) == pytest.approx(r.volume)


def test_concurrent_same_order_once(store, settings, signal, quote, spec, account):
    publish(store, signal)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: Execution(store, settings).submit(signal, quote, spec, account, NOW), range(4))
        )
    assert len(store.rows("SELECT * FROM orders")) == 1
    assert len(store.rows("SELECT * FROM fills")) == 1
    assert sum(r.get("duplicate", False) for r in results) == 3


def test_partial_profits_and_breakeven_persist(store, settings, signal, quote, spec, account):
    publish(store, signal)
    engine = Execution(store, settings)
    engine.submit(signal, quote, spec, account, NOW)
    engine.mark(
        Quote(symbol=signal.symbol, time=NOW + timedelta(minutes=1), bid=110, ask=110.1),
        NOW + timedelta(minutes=1),
    )
    position = json.loads(store.rows("SELECT payload FROM positions")[0]["payload"])
    assert position["remaining_volume"] == pytest.approx(position["original_volume"] * 0.5)
    assert position["stop"] == position["entry"]
    resumed = Execution(Store(store.path), settings)
    resumed.mark(
        Quote(symbol=signal.symbol, time=NOW + timedelta(minutes=2), bid=130, ask=130.1),
        NOW + timedelta(minutes=2),
    )
    assert store.rows("SELECT status FROM signals")[0]["status"] == "Closed"
    assert len(store.rows("SELECT * FROM fills")) == 4
    assert trades(store)[0]["realized_r"] > 0
    assert analytics(store)["closed_trades"] == 1


def test_kill_survives_restart(store, settings, signal, quote, spec, account):
    publish(store, signal)
    store.set_state("kill", True)
    r = Execution(Store(store.path), settings).submit(signal, quote, spec, account, NOW)
    assert r["status"] == "rejected" and not store.rows("SELECT * FROM orders")


def test_live_requires_explicit_validation(store, settings, signal, quote, spec, account):
    settings = settings.model_copy(update={"mode": "live"})
    r = size_trade(settings, signal, quote, spec, account.model_copy(update={"mode": "real"}), NOW)
    assert not r.accepted and "live_not_authorized" in r.reasons


def test_missing_mandatory_evidence_cannot_execute(settings, signal, quote, spec, account):
    incomplete = signal.model_copy(
        update={"evidence": tuple(e for e in signal.evidence if e.rule != "external_qm")}
    )
    result = size_trade(settings, incomplete, quote, spec, account, NOW)
    assert not result.accepted and "mandatory_strategy_evidence_missing" in result.reasons


def test_concurrent_different_signals_respect_position_cap(store, settings, signal, quote, spec, account):
    from uuid import uuid4
    from msnr.domain import fingerprint

    signals = []
    for i in range(5):
        s = signal.model_copy(
            update={"id": str(uuid4()), "fingerprint": fingerprint(i), "structure_ids": (str(i),)}
        )
        publish(store, s)
        signals.append(s)
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda s: Execution(store, settings).submit(s, quote, spec, account, NOW), signals))
    assert len(store.rows("SELECT * FROM positions WHERE status='open'")) == 3


def test_ambiguous_order_never_retried(store, settings, signal, quote, spec, account):
    class Broker:
        calls = 0

        def place(self, *args):
            self.calls += 1
            raise TimeoutError()

    broker = Broker()
    settings = settings.model_copy(update={"mode": "demo"})
    account = account.model_copy(update={"mode": "demo"})
    publish(store, signal)
    e = Execution(store, settings, broker)
    assert e.submit(signal, quote, spec, account, NOW)["status"] == "unknown"
    e.submit(signal, quote, spec, account, NOW)
    assert broker.calls == 1 and store.state("suspended")
