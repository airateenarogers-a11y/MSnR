import json
import os
import shutil
import signal
import time

import httpx
import pytest

from msnr.desktop import InstanceLock, Supervisor, Vault, protect_secret
from msnr.store import Store


@pytest.fixture(params=["paper", "demo"])
def desktop(tmp_path, request):
    root = tmp_path / "installation with spaces"
    (root / "config").mkdir(parents=True)
    shutil.copyfile("config/default.json", root / "config/default.json")
    supervisor = Supervisor(
        root,
        {
            "operator": "operator-test-" + "x" * 32,
            "bridge": "bridge-test-" + "y" * 32,
            "webhook": "",
            "terminal": "",
        },
        mode=request.param,
    )
    yield supervisor
    supervisor.close()


def test_repeat_start_auth_and_shutdown_release_actual_lease(desktop):
    desktop.start()
    original = {role: p.pid for role, p in desktop.processes.items()}
    desktop.start()
    assert original == {role: p.pid for role, p in desktop.processes.items()}
    with httpx.Client(trust_env=False) as client:
        assert client.get(desktop.url + "/api/status").status_code == 401
        response = client.get(
            desktop.url + "/api/status",
            headers={"Authorization": "Bearer " + desktop.credentials["operator"]},
        )
        assert response.json()["mode"] == desktop.mode
    store = Store(desktop.database)
    for _ in range(50):
        if store.state("worker_lease"):
            break
        time.sleep(0.1)
    assert store.state("worker_lease")
    desktop.close()
    assert store.state("worker_lease") is None
    assert store.verify_chain()
    assert not list(desktop.state.glob("stop-*"))


def test_crashed_worker_restarts_without_waiting_ten_minutes(desktop):
    desktop.start()
    store = Store(desktop.database)
    old = store.state("worker_lease")
    process = desktop.processes["worker"]
    if os.name == "nt":
        # Kill the actual interpreter, which can differ from the venv redirector.
        os.kill(old["pid"], signal.SIGTERM)
    else:
        process.kill()
    process.wait(timeout=5)
    assert "Worker stopped" in desktop.worker_problem()
    assert store.state("worker_lease") == old
    desktop.start()
    assert desktop.processes["worker"].pid != process.pid
    assert store.state("worker_lease")["session"] == desktop.worker_session
    assert store.rows("SELECT * FROM events WHERE kind='worker.lease_recovered'")


def test_worker_launch_handshake_handles_redirector_pid(desktop, monkeypatch):
    from datetime import timedelta
    from types import SimpleNamespace
    from msnr.clock import iso, utcnow

    desktop.worker_session = "this-launch"
    desktop.processes["worker"] = SimpleNamespace(pid=123, poll=lambda: None)
    store = Store(desktop.database)
    lease = {"pid": 456, "session": "this-launch", "until": iso(utcnow() + timedelta(minutes=10))}
    store.set_state("worker_lease", lease)
    try:
        desktop.wait_worker(timeout=0.2)
        lease["session"] = "another-launch"
        store.set_state("worker_lease", lease)
        with pytest.raises(RuntimeError, match="startup has not been confirmed"):
            desktop.wait_worker(timeout=0.2)
    finally:
        desktop.processes.pop("worker")


@pytest.mark.skipif(os.name != "nt", reason="Windows job trees include the venv redirector")
def test_stopping_orphaned_redirector_ends_actual_worker(desktop):
    from msnr.process_identity import identity

    desktop.start()
    lease = Store(desktop.database).state("worker_lease")
    process = desktop.processes["worker"]
    process.kill()
    process.wait(timeout=5)
    desktop.stop_process("worker")
    deadline = time.monotonic() + 5
    while identity(lease["pid"]) == lease["process_identity"] and time.monotonic() < deadline:
        time.sleep(0.1)
    assert identity(lease["pid"]) != lease["process_identity"]
    desktop.start()


def test_reconnect_restarts_a_dead_worker_even_after_connection_flag(desktop, monkeypatch):
    from types import SimpleNamespace

    terminal = desktop.state / "terminal64.exe"
    terminal.touch()
    desktop.credentials["terminal"] = str(terminal)
    desktop.feed_connected = True
    desktop.processes["worker"] = SimpleNamespace(poll=lambda: 1, returncode=1)
    started = []
    monkeypatch.setattr(desktop, "stop_process", lambda role: desktop.processes.pop(role, None))
    monkeypatch.setattr(desktop, "start_process", lambda role, feed=False: started.append((role, feed)))
    monkeypatch.setattr(desktop, "wait_worker", lambda: None)
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"mode": "demo", "hedging": True, "trading_allowed": True})
            ),
            **kw,
        ),
    )
    assert "Worker running" in desktop.connect() or desktop.mode == "paper"
    assert ("worker", True) in started


def test_inherited_live_flags_and_broker_password_are_not_used(desktop, monkeypatch):
    monkeypatch.setenv("MSNR_BRIDGE_ALLOW_LIVE", "EXPLICITLY_AUTHORIZED")
    monkeypatch.setenv("MT5_PASSWORD", "unrelated-account-password")
    monkeypatch.setenv("MSNR_DB", "/unrelated/ledger.db")
    env = desktop.environment()
    assert "MSNR_BRIDGE_ALLOW_LIVE" not in env
    assert "MT5_PASSWORD" not in env
    assert "MSNR_BRIDGE_URL" not in env
    assert env["MSNR_DB"] == str(desktop.database)


def test_live_config_refused_on_restart(desktop):
    data = json.loads(desktop.config.read_text())
    data["mode"] = "live"
    desktop.config.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="paper"):
        desktop.start_process("worker")
    assert not desktop.processes


def test_only_one_control_window(tmp_path):
    first = InstanceLock(tmp_path / "instance.lock")
    try:
        with pytest.raises(RuntimeError, match="already running"):
            InstanceLock(tmp_path / "instance.lock")
    finally:
        first.close()
    second = InstanceLock(tmp_path / "instance.lock")
    second.close()


def test_corrupt_credentials_are_never_silently_replaced(tmp_path):
    def codec(value, decrypt=False):
        return value[::-1]

    vault = Vault(tmp_path / "vault", codec=codec)
    original = vault.read()
    assert vault.read() == original
    assert original["operator"].encode() not in vault.path.read_bytes()
    vault.path.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        vault.read()
    assert vault.path.read_bytes() == b"corrupt"


def test_unconfigured_terminal_keeps_worker_disconnected(desktop):
    assert "Choose" in desktop.connect()
    assert not desktop.feed_connected
    assert "bridge" not in desktop.processes


@pytest.mark.parametrize(
    "account,connected",
    [
        ({"mode": "real", "hedging": True, "trading_allowed": True}, False),
        ({"mode": "demo", "hedging": False, "trading_allowed": True}, False),
        ({"mode": "demo", "hedging": True, "trading_allowed": True}, True),
    ],
)
def test_only_hedging_demo_account_connects(desktop, monkeypatch, account, connected):
    terminal = desktop.state / "terminal64.exe"
    terminal.touch()
    desktop.credentials["terminal"] = str(terminal)
    started = []
    monkeypatch.setattr(desktop, "start_process", lambda role, feed=False: started.append((role, feed)))
    monkeypatch.setattr(desktop, "wait_worker", lambda: None)
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=account)), **kw
        ),
    )
    desktop.connect()
    assert desktop.feed_connected is connected
    assert (("worker", True) in started) is connected


def test_demo_orders_wait_for_terminal_permissions(desktop, monkeypatch):
    if desktop.mode != "demo":
        return
    terminal = desktop.state / "terminal64.exe"
    terminal.touch()
    desktop.credentials["terminal"] = str(terminal)
    monkeypatch.setattr(desktop, "start_process", lambda *_: None)
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"mode": "demo", "hedging": True, "trading_allowed": False}
                )
            ),
            **kw,
        ),
    )
    assert "Enable MT5 Algo Trading" in desktop.connect()
    assert not desktop.feed_connected


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI requires a Windows user profile")
def test_windows_dpapi_roundtrip_and_randomized_ciphertext():
    secret = b"test-credential-never-used-for-a-service"
    protected = protect_secret(secret)
    assert secret not in protected
    assert protect_secret(protected, decrypt=True) == secret
    assert protected != protect_secret(secret)


def test_requested_stop_file_releases_worker_lease(settings, tmp_path, monkeypatch):
    from msnr.worker import Worker
    from msnr.clock import utcnow

    store = Store(tmp_path / "worker.db")
    worker = Worker(store, settings)
    worker.lease(utcnow())
    stop = tmp_path / "stop"
    stop.touch()
    monkeypatch.setenv("MSNR_WORKER_STOP_FILE", str(stop))
    monkeypatch.setattr("msnr.worker.os_signal.signal", lambda *_: None)
    worker.run()
    assert store.state("worker_lease") is None
