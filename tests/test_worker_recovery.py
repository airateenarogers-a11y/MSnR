from datetime import timedelta
import os
import socket
from types import SimpleNamespace

import pytest

from msnr.clock import iso, utcnow
from msnr.process_identity import identity
from msnr.store import Store
from msnr.worker import Worker, LeaseUnavailable, WorkerStopping


def test_process_identity_proves_current_process_alive():
    assert identity(os.getpid())
    assert identity(os.getpid()) == identity(os.getpid())


def test_live_worker_lease_is_never_taken(settings, tmp_path):
    store = Store(tmp_path / "live.db")
    first, second = Worker(store, settings), Worker(store, settings)
    now = utcnow()
    first.lease(now)
    original = store.state("worker_lease")
    with pytest.raises(LeaseUnavailable):
        second.lease(now)
    second.close()
    assert store.state("worker_lease") == original
    first.close()


def test_legacy_lease_waits_for_expiry(settings, tmp_path):
    store = Store(tmp_path / "legacy.db")
    now = utcnow()
    original = {"owner": "legacy-owner", "until": iso(now + timedelta(minutes=10))}
    store.set_state("worker_lease", original)
    worker = Worker(store, settings)
    with pytest.raises(LeaseUnavailable):
        worker.lease(now)
    assert store.state("worker_lease") == original
    worker.lease(now + timedelta(minutes=11))
    assert store.state("worker_lease")["owner"] == worker.owner
    worker.close()


@pytest.mark.parametrize("observed", [None, "different-process-start-time"])
def test_proven_dead_or_reused_pid_is_recovered(settings, tmp_path, monkeypatch, observed):
    store = Store(tmp_path / "dead.db")
    now = utcnow()
    worker = Worker(store, settings)
    store.set_state(
        "worker_lease",
        {
            "owner": "old-owner",
            "until": iso(now + timedelta(minutes=10)),
            "pid": 4567,
            "host": socket.gethostname(),
            "process_identity": "prior-process-start-time",
        },
    )
    monkeypatch.setattr("msnr.worker.identity", lambda _: observed)
    worker.lease(now)
    assert store.state("worker_lease")["owner"] == worker.owner
    assert store.rows("SELECT * FROM events WHERE kind='worker.lease_recovered'")
    worker.close()


def test_inaccessible_owner_is_not_assumed_dead(settings, tmp_path, monkeypatch):
    store = Store(tmp_path / "unknown.db")
    worker = Worker(store, settings)
    now = utcnow()
    original = {
        "owner": "unknown-owner",
        "until": iso(now + timedelta(minutes=10)),
        "pid": 4567,
        "host": socket.gethostname(),
        "process_identity": "protected-process",
    }
    store.set_state("worker_lease", original)

    def denied(_):
        raise PermissionError("Access denied")

    monkeypatch.setattr("msnr.worker.identity", denied)
    with pytest.raises(LeaseUnavailable):
        worker.lease(now)
    assert store.state("worker_lease") == original


def test_stop_interrupts_history_fetch_before_next_request(settings, tmp_path):
    worker = Worker(Store(tmp_path / "stop.db"), settings)
    calls = []

    def bars(symbol, timeframe, count):
        calls.append(timeframe)
        worker.stop_event.set()
        return []

    worker.bridge = SimpleNamespace(bars=bars)
    with pytest.raises(WorkerStopping):
        worker._bars("XAUUSDm")
    assert len(calls) == 1
