from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from msnr.bridge import create_bridge
from msnr.diagnostics import probe
from msnr.integrations.mt5 import MT5Bridge, Terminal
from msnr.market_health import MarketDataUnavailable, TerminalReadError
from msnr.worker import Worker
from conftest import NOW, candle
from test_bridge_and_worker import FakeTerminal


def native_module():
    rates = [
        dict(
            time=int((NOW - timedelta(minutes=i)).timestamp()),
            open=100,
            high=102,
            low=99,
            close=101,
            tick_volume=1,
        )
        for i in range(5, 0, -1)
    ]
    calls = []
    mt = SimpleNamespace(
        TIMEFRAME_M1=1,
        ACCOUNT_TRADE_MODE_DEMO=0,
        ACCOUNT_MARGIN_MODE_RETAIL_HEDGING=2,
        initialize=lambda **kw: True,
        shutdown=lambda: None,
        last_error=lambda: (-4, "missing"),
        symbol_info=lambda s: SimpleNamespace(visible=True),
        symbol_select=lambda *a: pytest.fail("Visible symbols must not be repeatedly selected"),
        symbol_info_tick=lambda s: SimpleNamespace(time_msc=int(NOW.timestamp() * 1000), bid=100, ask=100.1),
        account_info=lambda: SimpleNamespace(
            login=123456789,
            trade_mode=0,
            balance=1000,
            equity=1000,
            margin_free=1000,
            currency="USD",
            trade_allowed=True,
            trade_expert=True,
            margin_mode=2,
        ),
        terminal_info=lambda: SimpleNamespace(connected=True, trade_allowed=True, tradeapi_disabled=False),
        symbols_get=lambda: [SimpleNamespace(name="XAUUSDm", description="Gold", trade_mode=4)],
    )

    def copy(symbol, timeframe, start, count):
        calls.append(count)
        return rates[-count:]

    mt.copy_rates_from_pos = copy
    return mt, rates, calls


def test_native_history_updates_tail_and_never_uses_stale_data_after_failure():
    mt, rates, calls = native_module()
    terminal = Terminal(mt)
    terminal.bars("XAUUSDm", "M1", 500)
    rates[-1]["close"] = 100.5
    bars = terminal.bars("XAUUSDm", "M1", 500)
    assert calls == [500, 3]
    assert len(bars) == 5 and bars[-1].close == 100.5
    copy = mt.copy_rates_from_pos
    mt.copy_rates_from_pos = lambda *a: None
    with pytest.raises(TerminalReadError) as error:
        terminal.bars("XAUUSDm", "M1", 500)
    assert error.value.details["native_code"] == -4
    assert error.value.details["scope"] == "symbol"
    mt.copy_rates_from_pos = copy
    terminal.bars("XAUUSDm", "M1", 500)
    assert calls[-1] == 500


def test_history_reload_after_gap_and_periodic_refresh(monkeypatch):
    mt, rates, calls = native_module()
    terminal = Terminal(mt)
    terminal.bars("XAUUSDm", "M1", 500)
    for rate in rates:
        rate["time"] += 600
    terminal.bars("XAUUSDm", "M1", 500)
    assert calls == [500, 3, 500]
    clock = time.monotonic()
    monkeypatch.setattr("msnr.integrations.mt5.time.monotonic", lambda: clock + 301)
    terminal.bars("XAUUSDm", "M1", 500)
    assert calls[-1] == 500


def test_native_account_switch_invalidates_history_and_reports_python_permission():
    mt, _, _ = native_module()
    terminal = Terminal(mt)
    terminal.account()
    terminal.bars("XAUUSDm", "M1", 500)
    assert terminal.history
    original = mt.account_info
    mt.account_info = lambda: SimpleNamespace(**(vars(original()) | {"login": 987654321}))
    mt.terminal_info = lambda: SimpleNamespace(connected=True, trade_allowed=True, tradeapi_disabled=True)
    assert not terminal.account()["trading_allowed"]
    assert not terminal.history


def test_read_timeouts_are_reported_with_context_and_orders_are_not_retried():
    seen = []

    def stalled(request):
        seen.append(request)
        raise httpx.ReadTimeout("test only", request=request)

    client = httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(stalled))
    bridge = MT5Bridge("http://127.0.0.1", token="test", client=client)
    with pytest.raises(MarketDataUnavailable) as failure:
        bridge.bars("ETHUSDm", "H4", 500)
    assert failure.value.details["operation"] == "bars"
    assert failure.value.details["timeframe"] == "H4"
    assert failure.value.details["symbol"] == "ETHUSDm"
    assert seen[-1].extensions["timeout"]["read"] == 90
    with pytest.raises(httpx.ReadTimeout):
        bridge.modify("test-command", 1, 95, 110)
    assert len(seen) == 2


def test_loopback_bridge_ignores_system_http_proxy(monkeypatch):
    seen = {}

    def client(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr("msnr.integrations.mt5.httpx.Client", client)
    MT5Bridge("http://127.0.0.1:8765", token="test")
    assert seen["trust_env"] is False


def test_slow_native_history_does_not_queue_other_requests(tmp_path, spec, quote, monkeypatch):
    monkeypatch.setenv("MSNR_BRIDGE_TOKEN", "x" * 32)
    terminal = FakeTerminal(spec, quote)
    entered, release = threading.Event(), threading.Event()

    def slow(*args):
        entered.set()
        assert release.wait(5)
        return [candle(-1, 100, 102, 99, 101)]

    terminal.bars = slow
    with TestClient(create_bridge(terminal, tmp_path / "bridge.db")) as client:
        client.headers["Authorization"] = "Bearer " + "x" * 32
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.get, "/bars", params={"symbol": "XAUUSDm", "timeframe": "M1"})
            try:
                assert entered.wait(2)
                started = time.monotonic()
                busy = client.get("/account")
                assert busy.status_code == 503 and busy.json()["detail"]["code"] == "mt5_busy"
                assert time.monotonic() - started < 1
                diagnostic = client.get("/diagnostics").json()
                assert diagnostic["active_call"]["operation"] == "bars"
                assert diagnostic["active_call"]["timeframe"] == "M1"
            finally:
                release.set()
            assert pending.result(timeout=2).status_code == 200
        assert client.get("/account").status_code == 200
        assert client.get("/diagnostics").json()["active_call"] is None


def test_native_error_survives_http_bridge(tmp_path, spec, quote, monkeypatch):
    monkeypatch.setenv("MSNR_BRIDGE_TOKEN", "x" * 32)
    terminal = FakeTerminal(spec, quote)

    def missing(*args):
        raise TerminalReadError(
            "copy_rates_from_pos",
            symbol="ETHUSDm",
            timeframe="MN1",
            native_code=-4,
            code="history_not_ready",
            scope="symbol",
        )

    terminal.bars = missing
    with TestClient(create_bridge(terminal, tmp_path / "bridge.db")) as client:
        client.headers["Authorization"] = "Bearer " + "x" * 32
        response = client.get("/bars", params={"symbol": "ETHUSDm", "timeframe": "MN1"})
        assert response.status_code == 503
        assert response.json()["detail"]["native_code"] == -4
        assert client.get("/diagnostics").json()["last_error"]["operation"] == "copy_rates_from_pos"


def test_feed_backoff_is_persistent_and_alert_is_consolidated(store, settings, monkeypatch):
    clock = [NOW]
    monkeypatch.setattr("msnr.worker.utcnow", lambda: clock[0])
    calls = []

    def timeout():
        calls.append("account")
        raise MarketDataUnavailable("account", code="ReadTimeout")

    bridge = SimpleNamespace(account=timeout, close=lambda: None)
    worker = Worker(store, settings, bridge)
    worker.once()
    assert store.state("feed_blocked") is True
    assert not store.state("suspended", False)
    worker.once()
    assert calls == ["account"]
    worker.close()
    restarted = Worker(store, settings, bridge)
    restarted.once()
    assert calls == ["account"]
    clock[0] += timedelta(seconds=20)
    restarted.once()
    assert calls == ["account", "account"]
    assert len(store.rows("SELECT * FROM outbox WHERE event_key LIKE 'feed:%'")) == 1
    assert store.state("worker_health")["status"] == "waiting_for_mt5"


def test_alias_uses_broker_symbol_and_only_checks_m1_until_a_new_candle(
    store, settings, spec, quote, monkeypatch
):
    monkeypatch.setattr("msnr.worker.utcnow", lambda: NOW)
    instrument = settings.instruments[0].model_copy(
        update={"symbol": "TSLA", "aliases": ("TSLAm",), "peer": ()}
    )
    settings = settings.model_copy(update={"instruments": (instrument,)})
    calls, evaluations = [], []

    def bars(symbol, tf, count):
        calls.append((symbol, tf))
        return [candle(-1, 100, 102, 99, 101).model_copy(update={"symbol": symbol})]

    bridge = SimpleNamespace(
        account=lambda: {"id": "demo", "mode": "demo", "balance": 100000, "equity": 100000},
        symbols=lambda: [{"symbol": "TSLAm"}],
        quote=lambda s: quote.model_copy(update={"symbol": s}),
        spec=lambda s: spec.model_copy(update={"symbol": s}),
        bars=bars,
    )
    worker = Worker(store, settings, bridge)

    def evaluate(snapshot):
        evaluations.append(snapshot.symbol)
        assert worker.engine.settings.instrument(snapshot.symbol).symbol == "TSLAm"
        return SimpleNamespace(signals=[], rejected=[], structures={})

    worker.engine.evaluate = evaluate
    worker.once()
    assert evaluations == ["TSLAm"]
    assert store.state("instrument_status")["TSLA"]["broker_symbol"] == "TSLAm"
    calls.clear()
    store.set_state("runtime_instruments", ["TSLA"])
    worker.once()
    assert calls == [("TSLAm", "M1")]
    assert evaluations == ["TSLAm"]


def test_native_probe_reports_prices_without_account_ids_or_credentials(settings, tmp_path):
    mt, _, _ = native_module()
    report = probe(Terminal(mt), [settings.instruments[0]], tmp_path / "check.json")
    assert report["status"] == "complete"
    assert report["symbols"][0]["status"] == "readable"
    assert report["symbols"][0]["quote"]["bid"] == 100
    assert "123456789" not in json.dumps(report)
    assert report["symbols"][0]["history"]["count"] == 5
    assert json.loads((tmp_path / "check.json").read_text()) == report


def test_reconciliation_read_failure_is_not_a_successful_empty_snapshot():
    mt, _, _ = native_module()
    mt.positions_get = lambda: []
    mt.orders_get = lambda: []
    mt.history_deals_get = lambda start, end: None
    with pytest.raises(TerminalReadError) as failure:
        Terminal(mt).reconcile()
    assert failure.value.details["operation"] == "history_deals_get"


def test_pending_old_failure_notices_are_superseded_without_deletion(store, settings, monkeypatch):
    monkeypatch.delenv("MSNR_BRIDGE_URL", raising=False)
    store.enqueue("failure:ETHUSDm:old-hour", {"summary": "old failure"}, NOW)
    store.enqueue("failure:USOILm:old-hour", {"summary": "old failure"}, NOW)
    worker = Worker(store, settings)
    worker.once()
    rows = store.rows("SELECT * FROM outbox")
    assert len(rows) == 2 and all(r["status"] == "cancelled" for r in rows)
    assert store.rows("SELECT * FROM events WHERE kind='notification.legacy_failures_superseded'")
    assert store.verify_chain()


def test_feed_block_prevents_execution_without_clearing_other_controls(
    store, settings, signal, quote, spec, account
):
    from msnr.execution import Execution

    store.add_signal(signal)
    store.transition(signal.id, "Published", {}, NOW)
    store.set_state("feed_blocked", True)
    store.set_state("suspended", False)
    result = Execution(store, settings).submit(signal, quote, spec, account, NOW)
    assert result["status"] == "rejected"
    assert not store.rows("SELECT * FROM orders")
    assert not store.state("suspended")
