from datetime import timedelta
import json


from msnr.execution import Execution
from msnr.risk import phase_for, account_controls, size_trade
from msnr.strategy.engine import Evaluation
from msnr.backtest import replay
from msnr.store import Store
from conftest import NOW, candle


def test_phase_thresholds_and_demote(settings):
    p = settings.policy
    assert phase_for(103000, 100000, 103000, 0, p) == 2
    assert phase_for(108001, 100000, 108001, 0, p) == 3
    assert phase_for(104000, 100000, 104000, 3, p, 2) == 3
    assert phase_for(102000, 100000, 108000, 3, p, 3) == 1


def test_cooldown_and_reality_check(store, settings, account, signal, quote, spec):
    rows = [{"closed_at": NOW.isoformat(), "net": 1000, "realized_r": 3, "risk_phase": 1}]
    controls = account_controls(store, settings, rows, NOW, 101000, 100000, 101000, "paper")
    assert controls["cooldown_until"] == NOW + timedelta(minutes=10)
    assert controls["reality_check_required"]
    r = size_trade(settings, signal, quote, spec, account.model_copy(update=controls), NOW)
    assert not r.accepted and "manual_reality_check_required" in r.reasons
    store.set_state("reality_confirmed_at", (NOW + timedelta(minutes=1)).isoformat())
    assert not account_controls(
        store, settings, rows, NOW + timedelta(minutes=11), 101000, 100000, 101000, "paper"
    )["reality_check_required"]


def test_broker_deals_recover_unknown_order(store, settings, signal, quote, spec, account):
    settings = settings.model_copy(update={"mode": "demo"})
    account = account.model_copy(update={"mode": "demo"})
    store.add_signal(signal)
    store.transition(signal.id, "Published", {"test": True}, NOW)

    class Broker:
        order = None

        def place(self, command_id, *args):
            self.order = command_id
            raise TimeoutError()

        def reconcile(self):
            return {
                "complete": True,
                "positions": [{"ticket": 456, "volume": 0.6, "sl": 95}],
                "deals": [
                    {
                        "ticket": 123,
                        "position_id": 456,
                        "order": 456,
                        "comment": "msnr:" + self.order.replace("-", "")[:20],
                        "entry": 0,
                        "volume": 0.6,
                        "price": 100.1,
                        "profit": 0,
                        "commission": -2.1,
                        "time": int(NOW.timestamp()),
                    }
                ],
            }

    broker = Broker()
    e = Execution(store, settings, broker)
    assert e.submit(signal, quote, spec, account, NOW)["status"] == "unknown"
    result = e.reconcile(NOW + timedelta(seconds=1))
    assert result["status"] == "reconciled"
    assert store.rows("SELECT status FROM signals")[0]["status"] == "Active"
    e.reconcile(NOW + timedelta(seconds=2))
    assert len(store.rows("SELECT * FROM fills")) == 1
    assert store.state("suspended")  # Operator review clears critical-error suspension, never blind recovery.


def test_replay_pessimistic_ambiguous_bar_and_no_future(settings, spec, signal, tmp_path):
    class FixtureEvaluator:
        called = 0

        def evaluate(self, snap):
            self.called += 1
            assert all(b.end <= snap.now for bs in snap.bars.values() for b in bs)
            if self.called == 1:
                return Evaluation(signals=[signal])
            return Evaluation()

    bs = [candle(0, 100, 140, 90, 110, tf="M1", minutes=1)]
    path = tmp_path / "execution-replay.db"
    result = replay(
        settings,
        {"XAUUSDm": {"M1": bs}},
        {"XAUUSDm": spec},
        path,
        {"XAUUSDm": 0.1},
        evaluator=FixtureEvaluator(),
    )
    assert result["closed_trades"] == 1 and result["losses"] == 1
    fills = [json.loads(r["payload"]) for r in Store(path).rows("SELECT payload FROM fills")]
    assert [f["kind"] for f in fills] == ["entry", "stop"]
    assert fills[-1]["price"] < 95  # Gap/slippage is adverse, not an optimistic stop fill.
