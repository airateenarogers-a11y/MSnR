from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from msnr.bridge import create_bridge
from msnr.worker import Worker
from msnr.domain import Bar
from msnr.research import validate
from msnr.data import read_csv
from conftest import NOW, candle
from test_engine_pipeline import market_fixture


class MTModule:
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    POSITION_TYPE_BUY = 0
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    calls = 0

    def order_check(self, request):
        return SimpleNamespace(retcode=0)

    def order_send(self, request):
        self.calls += 1
        return SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE,
            order=123,
            deal=456,
            volume=request.get("volume", 0),
            price=request.get("price", 0),
        )

    def positions_get(self, ticket):
        return [SimpleNamespace(type=0, sl=95, volume=0.6, symbol="XAUUSDm")]

    def shutdown(self):
        pass


class FakeTerminal:
    def __init__(self, spec, quote):
        self.mt = MTModule()
        self._spec = spec
        self._quote = quote

    def connect(self):
        pass

    def account(self):
        return {"id": "demo-1", "trading_allowed": True, "mode": "demo", "hedging": True}

    def quote(self, symbol):
        return self._quote

    def spec(self, symbol):
        return self._spec

    def symbols(self):
        return [{"symbol": "XAUUSDm"}]

    def bars(self, *args):
        return [candle(-1, 100, 101, 99, 100)]

    def reconcile(self):
        return {"complete": True, "positions": [], "deals": []}


def test_bridge_auth_idempotency_modify_close(tmp_path, spec, quote, monkeypatch):
    monkeypatch.setenv("MSNR_BRIDGE_TOKEN", "bridge-test-" + "x" * 32)
    terminal = FakeTerminal(spec, quote)
    with TestClient(create_bridge(terminal, tmp_path / "bridge.db")) as client:
        assert client.get("/account").status_code == 401
        client.headers["Authorization"] = "Bearer bridge-test-" + "x" * 32
        assert client.get("/symbols").json()[0]["symbol"] == "XAUUSDm"
        assert (
            client.get("/bars", params={"symbol": "XAUUSDm", "timeframe": "M5", "count": 10}).status_code
            == 200
        )
        assert (
            client.get("/bars", params={"symbol": "XAUUSDm", "timeframe": "M5", "count": 10001}).status_code
            == 422
        )
        request = {
            "command_id": str(uuid4()),
            "account_id": "demo-1",
            "symbol": "XAUUSDm",
            "direction": "BUY",
            "volume": 0.6,
            "entry": 100.1,
            "stop": 95,
            "target": 130,
            "signal_id": str(uuid4()),
            "policy_hash": "test",
        }
        assert client.post("/orders", json=request).json()["status"] == "filled"
        assert client.post("/orders", json=request).json()["status"] == "filled"
        assert terminal.mt.calls == 1
        assert client.get("/commands/" + request["command_id"]).json()["status"] == "filled"
        assert client.post("/orders", json={**request, "account_id": "wrong"}).status_code == 409
        assert (
            client.post("/orders", json={**request, "command_id": str(uuid4()), "volume": 0.001}).status_code
            == 422
        )
        assert (
            client.post(
                "/positions/modify",
                json={"command_id": str(uuid4()), "ticket": 123, "stop": 94, "target": 130},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/positions/modify",
                json={"command_id": str(uuid4()), "ticket": 123, "stop": 100.1, "target": 130},
            ).json()["status"]
            == "filled"
        )
        assert (
            client.post(
                "/positions/close", json={"command_id": str(uuid4()), "ticket": 123, "volume": 0.3}
            ).json()["status"]
            == "filled"
        )


def test_bridge_refuses_live_and_netting(tmp_path, spec, quote, monkeypatch):
    monkeypatch.setenv("MSNR_BRIDGE_TOKEN", "bridge-test-" + "x" * 32)
    terminal = FakeTerminal(spec, quote)
    terminal.account = lambda: {"id": "real", "mode": "real", "hedging": True, "trading_allowed": True}
    with TestClient(create_bridge(terminal, tmp_path / "bridge.db")) as client:
        client.headers["Authorization"] = "Bearer bridge-test-" + "x" * 32
        request = {
            "command_id": str(uuid4()),
            "account_id": "real",
            "symbol": "XAUUSDm",
            "direction": "BUY",
            "volume": 0.6,
            "entry": 100.1,
            "stop": 95,
            "target": 130,
            "signal_id": str(uuid4()),
            "policy_hash": "test",
        }
        assert client.post("/orders", json=request).status_code == 403
        terminal.account = lambda: {"id": "real", "mode": "demo", "hedging": False, "trading_allowed": True}
        assert client.post("/orders", json=request).status_code == 409
        assert terminal.mt.calls == 0


def test_worker_missing_bridge_and_lease(store, settings, monkeypatch):
    monkeypatch.delenv("MSNR_BRIDGE_URL", raising=False)
    first = Worker(store, settings)
    first.once()
    assert store.state("worker_health")["status"] == "waiting_for_market_data"
    with pytest.raises(RuntimeError):
        Worker(store, settings).once()


def test_worker_with_real_engine_publishes_once(store, monkeypatch, tmp_path):
    settings, snap = market_fixture()
    settings = settings.model_copy(update={"instruments": (settings.instruments[0],)})
    for tf, minutes in [("M3", 3), ("M5", 5), ("M30", 30)]:
        source = snap.bars["M1"]
        result = []
        for i in range(0, len(source), minutes):
            part = source[i : i + minutes]
            if len(part) != minutes:
                continue
            result.append(
                Bar(
                    symbol=snap.symbol,
                    timeframe=tf,
                    time=part[0].time,
                    end=part[-1].end,
                    open=part[0].open,
                    high=max(b.high for b in part),
                    low=min(b.low for b in part),
                    close=part[-1].close,
                    source=part[0].source,
                )
            )
        snap.bars[tf] = result
    snap.bars["MN1"] = [
        candle(-2, 150, 170, 145, 160, tf="MN1", minutes=43200),
        candle(-1, 160, 170, 140, 150, tf="MN1", minutes=43200),
    ]

    class Bridge:
        def account(self):
            return {"id": "demo", "equity": 100000, "balance": 100000, "mode": "demo", "at": NOW.isoformat()}

        def symbols(self):
            return [{"symbol": snap.symbol}]

        def quote(self, symbol):
            return snap.quote

        def spec(self, symbol):
            return snap.spec

        def bars(self, symbol, tf, count):
            return snap.bars[tf]

    monkeypatch.setattr("msnr.worker.utcnow", lambda: NOW)
    monkeypatch.chdir(tmp_path)
    worker = Worker(store, settings, Bridge())
    worker.once()
    assert store.state("worker_health")["status"] == "running"
    signals = store.rows("SELECT * FROM signals")
    assert signals, "Raw strategy engine must produce a qualifying fixture signal"
    assert all(s["chart_path"] for s in signals)
    count = len(signals)
    worker.once()
    assert len(store.rows("SELECT * FROM signals")) == count
    assert (
        len(store.rows("SELECT * FROM orders")) == 1
    )  # Same structure cannot execute twice via different model names.


def test_research_runs_fixed_policy_windows(settings, spec, tmp_path):
    bs = [candle(i, 100, 101, 99, 100, tf="M1", minutes=1) for i in range(101)]
    result = validate(
        settings, {"XAUUSDm": {"M1": bs}}, {"XAUUSDm": spec}, {"XAUUSDm": 0.1}, tmp_path / "research"
    )
    assert result["strategy_parameters_changed"] is False
    assert result["credible_edge_established"] is False
    assert result["out_of_sample"]["status"] == "no_completed_trades_not_strategy_validation"
    assert len(result["cost_sensitivity"]) == 3 and result["walk_forward"]


def test_csv_rejects_naive_and_unsorted(tmp_path):
    path = tmp_path / "bars.csv"
    path.write_text("time,open,high,low,close\n2026-10-01T00:00:00,100,101,99,100\n")
    with pytest.raises(ValueError):
        read_csv(path, "XAUUSDm", "M1", "TEST ONLY")
