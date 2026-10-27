from datetime import timedelta
from msnr.config import load
from msnr.strategy.engine import Engine, Snapshot
from msnr.domain import Bar, Quote, SymbolSpec
from conftest import NOW, candle


def market_fixture():
    settings = load()
    settings = settings.model_copy(update={"policy": settings.policy.model_copy(update={"version": "v4"})})
    hstart = NOW - timedelta(hours=9)
    h = [
        (104, 105, 101, 102),
        (102, 106, 101, 105),
        (105, 111, 104, 110),
        (110, 111, 100, 101),
        (101, 102, 94, 95),
        (95, 100, 94, 99),
        (99, 113, 98, 112),
        (112, 114, 108, 110),
        (110, 111, 101, 103.5),
    ]
    h1 = [candle(i, *v, tf="H1", minutes=60, start=hstart) for i, v in enumerate(h)]
    d = [
        candle(-3, 110, 111, 98, 100, tf="D1", minutes=1440),
        candle(-2, 100, 108, 99, 105, tf="D1", minutes=1440),
        candle(-1, 103, 115, 94, 103.5, tf="D1", minutes=1440),
    ]
    m1 = []
    for index, hour in enumerate(h1):
        for minute in range(60):
            if index == 8:
                o = 110 + (103 - 110) * minute / 45 if minute < 45 else 103 + 0.5 * (minute - 45) / 15
                c = 110 + (103 - 110) * (minute + 1) / 45 if minute < 45 else 103 + 0.5 * (minute - 44) / 15
            else:
                o = hour.open + (hour.close - hour.open) * minute / 60
                c = hour.open + (hour.close - hour.open) * (minute + 1) / 60
            high = max(o, c)
            low = min(o, c)
            if minute == 0:
                high = hour.high
            if minute == (59 if index == 8 else 0):
                low = hour.low
            m1.append(candle(minute, o, high, low, c, tf="M1", minutes=1, start=hour.time))
    last = m1[-15:]
    m15 = [
        Bar(
            symbol="XAUUSDm",
            timeframe="M15",
            time=last[0].time,
            end=last[-1].end,
            open=last[0].open,
            high=max(b.high for b in last),
            low=min(b.low for b in last),
            close=last[-1].close,
            source="SYNTHETIC TEST ONLY",
        )
    ]
    # Future target fixtures: A -> RBS -> SBR, fresh opposing levels above entry.
    h4 = [
        candle(-4, 130, 131, 119, 120, tf="H4", minutes=240),
        candle(-3, 120, 126, 119, 125, tf="H4", minutes=240),
        candle(-2, 125, 126, 118, 119, tf="H4", minutes=240),
        candle(-1, 119, 119.5, 110, 115, tf="H4", minutes=240),
    ]
    w = [
        candle(-2, 140, 151, 139, 150, tf="W1", minutes=10080),
        candle(-1, 150, 151, 142, 145, tf="W1", minutes=10080),
    ]
    spec = SymbolSpec(
        symbol="XAUUSDm",
        tick_size=0.01,
        tick_value_loss=1,
        point=0.01,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        stops_distance=0.1,
        contract_size=100,
        trade_allowed=True,
        market_open=True,
        currency_profit="USD",
        currency_account="USD",
    )
    # Add old D1 resistance without affecting the final support/rejection sequence.
    d = [
        candle(-5, 125, 131, 124, 130, tf="D1", minutes=1440),
        candle(-4, 130, 131, 125, 126, tf="D1", minutes=1440),
    ] + d
    snap = Snapshot(
        NOW,
        "XAUUSDm",
        {"D1": d, "H1": h1, "H4": h4, "W1": w, "M1": m1, "M15": m15},
        spec,
        Quote(symbol="XAUUSDm", time=NOW, bid=103.4, ask=103.5),
    )
    return settings, snap


def test_raw_multitimeframe_pipeline_generates_valid_ls():
    settings, snap = market_fixture()
    result = Engine(settings).evaluate(snap)
    signal = next(s for s in result.signals if s.setup == "LS")
    # The fresh H1 SBR at 105 takes precedence over the farther H4 target at 120.
    assert signal.targets == (105, 130, 150)
    assert signal.stop == 91
    assert signal.rating == "B"
    assert all(e.outcome == "PASS" for e in signal.evidence)
    assert signal.chart_features


def test_post_breakout_source_retouch_invalidates_old_qm():
    settings, snap = market_fixture()
    snap.bars["M1"][-1] = snap.bars["M1"][-1].model_copy(update={"low": 99})
    result = Engine(settings).evaluate(snap)
    assert not result.signals
    assert any("external_qm:FAIL" in r.get("rules", []) for r in result.rejected)


def test_missing_confirmation_candle_blocks_engine():
    settings, snap = market_fixture()
    snap.bars["D1"][-1] = snap.bars["D1"][-1].model_copy(update={"close": 103})
    assert not Engine(settings).evaluate(snap).signals


def test_gap_in_confirmation_history_rejected():
    settings, snap = market_fixture()
    del snap.bars["M1"][-20]
    result = Engine(settings).evaluate(snap)
    assert not result.signals
    assert any("Missing lower-timeframe" in r.get("reason", "") for r in result.rejected)
