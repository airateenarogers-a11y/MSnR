from datetime import timedelta

import pytest

from msnr.data import series, aggregate_observed
from msnr.domain import Direction
from msnr.strategy.primitives import levels, quasimodos, qm_valid, rejection, ema, ema_badge, crt, fibonacci
from msnr.strategy.catalog import CATALOG, rating
from msnr.strategy.engine import gate, Engine, Snapshot
from conftest import NOW, candle


def test_body_junction_is_not_apex(settings):
    bs = [candle(0, 100, 108, 99, 105), candle(1, 105, 110, 101, 102)]
    a = levels(bs, 0.01, settings.policy)[0]
    assert a.price == 105 and a.apex == 110 and a.kind == "A"


def test_gap_same_color_junction_user_approved(settings):
    bs = [candle(0, 100, 106, 99, 105), candle(1, 105, 110, 104, 109)]
    gap = levels(bs, 0.01, settings.policy)[0]
    assert gap.kind == "GAP_BUY" and gap.price == 105


def test_no_junction_no_invented_level(settings):
    assert not levels([candle(0, 100, 106, 99, 105), candle(1, 105.1, 106, 99, 100)], 0.01, settings.policy)


def test_cc_is_immediate_third_candle(settings):
    bs = [candle(0, 105, 106, 98, 100), candle(1, 100, 106, 99, 105), candle(2, 105, 106, 99, 105.5)]
    v = levels(bs, 0.01, settings.policy)[0]
    assert v.price == 100 and v.repaired and v.fresh and v.touches == 1


def test_touch_later_does_not_repair(settings):
    bs = [
        candle(0, 105, 106, 98, 100),
        candle(1, 100, 106, 99, 105),
        candle(2, 105, 106, 103, 104),
        candle(3, 104, 107, 99, 106),
    ]
    v = levels(bs, 0.01, settings.policy)[0]
    assert not v.fresh and not v.repaired


def test_body_break_flips_and_refreshes(settings):
    bs = [candle(0, 105, 106, 98, 100), candle(1, 100, 106, 99, 105), candle(2, 105, 106, 98, 99)]
    v = levels(bs, 0.01, settings.policy)[0]
    assert v.kind == "SBR" and v.fresh and v.role == Direction.SELL and v.revision == 1


def test_bullish_qm_requires_body_close(settings):
    bs = [
        candle(0, 104, 105, 101, 102),
        candle(1, 102, 106, 101, 105),
        candle(2, 105, 111, 104, 110),
        candle(3, 110, 111, 100, 101),
        candle(4, 101, 102, 94, 95),
        candle(5, 95, 100, 94, 99),
        candle(6, 99, 112, 98, 109),
    ]
    assert not quasimodos(bs, 0.01, settings.policy)
    bs.append(candle(7, 109, 113, 108, 112))
    q = quasimodos(bs, 0.01, settings.policy)[0]
    assert q.direction == Direction.BUY and q.reference.price == 110
    assert qm_valid(q, bs[4].end, "SNR")
    assert not qm_valid(q, q.breakout.end, "SNR")
    assert not qm_valid(q, bs[1].time, "SNR")


def test_rejection_ratio_and_doji(settings):
    assert rejection(candle(0, 105, 107, 99, 106), 100, Direction.BUY, 0.01, 2)
    assert not rejection(candle(0, 105, 107, 104, 106), 105, Direction.BUY, 0.01, 2)
    assert not rejection(candle(0, 105, 107, 99, 105), 100, Direction.BUY, 0.01, 2)
    assert rejection(candle(0, 105, 107, 99, 106), 100, Direction.BUY, 0.01, None) is None


def test_ema_warmup_and_hold():
    assert ema([1] * 8) == [None] * 8
    assert ema([1] * 10) == [None] * 8 + [1, 1]
    assert ema_badge([], Direction.BUY, None) is None
    assert ema_badge([], Direction.BUY, 1) is False


def test_no_future_or_mixed_series():
    bs = [candle(0, 100, 101, 99, 100), candle(1, 100, 102, 99, 101)]
    assert series(bs, bs[0].end) == bs[:1]
    with pytest.raises(ValueError):
        series(bs + bs, NOW + timedelta(days=1))
    with pytest.raises(ValueError):
        series(bs, NOW + timedelta(days=1), symbol="EURUSDm")


def test_partial_htf_excludes_future_extreme():
    bs = [candle(0, 100, 101, 99, 100), candle(1, 100, 999, 99, 101)]
    p = aggregate_observed(bs, NOW, NOW + timedelta(hours=1), bs[0].end, "H1")
    assert p.high == 101


def test_unknown_required_never_passes():
    e = gate({"fresh": True, "smt": None}, ("fresh", "smt", "missing"), NOW)
    assert [x.outcome for x in e] == ["PASS", "UNKNOWN", "UNKNOWN"]


def test_catalog_all_named_models():
    assert len(CATALOG) == 18
    assert {"MISS", "DOUBLE_APEX", "SNRC1", "EX1", "EX2", "EX3", "EX4", "QM_TO_QM"} <= {
        m.name for m in CATALOG
    }
    assert "smt" not in next(m for m in CATALOG if m.name == "LS").requirements
    assert all("smt" in m.requirements for m in CATALOG if m.name in ("EX2", "EX3", "EX4"))


def test_rating_measures_facts_not_win_probability():
    assert rating({"one": True, "two": None, "three": False})[:2] == ("B", 33)
    assert rating({"one": None})[:2] == ("C", 0)


def test_missing_market_data_rejected(settings, spec, quote):
    result = Engine(settings).evaluate(Snapshot(NOW, "XAUUSDm", {}, spec, quote))
    assert not result.signals and result.rejected[0]["reason"] == "missing_closed_bars"


def test_invalid_ohlc_and_naive_time():
    with pytest.raises(ValueError):
        candle(0, 100, 99, 98, 100)
    with pytest.raises(ValueError):
        candle(0, 100, 101, 99, 100, start=NOW.replace(tzinfo=None))


def test_fibonacci_and_crt():
    assert fibonacci(100, 200)[1.893] == pytest.approx(289.3)
    assert crt(candle(0, 100, 105, 95, 101), candle(1, 101, 106, 99, 104)) == "sweep"
