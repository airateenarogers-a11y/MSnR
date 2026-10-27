"""V5 boundary and integration regressions; synthetic data are not performance evidence."""

from datetime import datetime, timedelta
from dataclasses import replace
from pathlib import Path
import hashlib
import json

import pytest

from msnr.clock import NY, quarter, session
from msnr.config import load, RiskLimits
from msnr.domain import Direction, Evidence
from msnr.risk import phase_for, size_trade
from msnr.strategy.catalog import catalog, requirements
from msnr.strategy.engine import Engine
from msnr.strategy.primitives import Level, fibonacci, quasimodos, qm_valid, ema_badge
from msnr.strategy.v5 import MAPPING, mapped_rejection, entry_badges, ote, q2_sweep
from conftest import NOW, candle
from test_engine_pipeline import market_fixture


def test_source_is_exact_and_every_section_is_traced():
    source = Path("docs/sources/strategy-v5.md").read_bytes()
    index = json.loads(Path("docs/requirements-v5.json").read_text())
    assert hashlib.sha256(source).hexdigest() == index["sha256"]
    assert len(index["sections"]) == 26
    assert all(row["text"].strip() in Path(index["source"]).read_text() for row in index["sections"])
    assert load().policy.version == "v5"


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, 1), (1349, 1), (1350, 2), (2699, 2), (2700, 3), (4049, 3), (4050, 4), (5399, 4), (5400, 1)],
)
def test_exact_micro_quarters(seconds, expected):
    now = datetime(2026, 7, 1, tzinfo=NY) + timedelta(seconds=seconds)
    assert quarter(now, "v5") == expected


@pytest.mark.parametrize("month", [1, 7])
def test_sessions_follow_new_york_dst(month):
    assert session(datetime(2026, month, 2, 19, 59, tzinfo=NY), "v5") == "off_session"
    assert session(datetime(2026, month, 2, 20, tzinfo=NY), "v5") == "asia"
    assert session(datetime(2026, month, 2, 8, tzinfo=NY), "v5") == "new_york_am"
    assert session(datetime(2026, month, 2, 13, tzinfo=NY), "v5") == "off_session"


@pytest.mark.parametrize(
    "equity,previous,wins,expected",
    [
        (101999, 1, 0, 1),
        (102000, 1, 0, 2),
        (100000, 1, 3, 2),
        (105000, 2, 0, 3),
        (104999, 2, 0, 2),
        (104000, 3, 0, 3),
        (104500, 3, 0, 1),
    ],
)
def test_evaluation_risk_thresholds(equity, previous, wins, expected):
    peak = 110000 if equity == 104500 else max(100000, equity)
    assert (
        phase_for(
            equity,
            100000,
            peak,
            0,
            load().policy,
            previous,
            limits=RiskLimits(evaluation_mode=True),
            phase1_wins=wins,
        )
        == expected
    )


def test_near_target_and_funded_cap_are_distinct():
    policy = load().policy
    assert (
        phase_for(
            104000,
            100000,
            104000,
            0,
            policy,
            2,
            limits=RiskLimits(evaluation_mode=True, evaluation_target_fraction=0.06),
        )
        == 3
    )
    assert phase_for(110000, 100000, 110000, 0, policy, 3, limits=RiskLimits()) == 2
    assert phase_for(100000, 100000, 100000, 0, policy, 1, limits=RiskLimits(), phase1_wins=3) == 1


def test_funded_sizing_caps_phase_three_account(signal, quote, spec, account):
    s = load()
    s = s.model_copy(update={"risk": s.risk.model_copy(update={"per_trade": 0.01})})
    model = next(x for x in catalog("v5") if x.name == "LS")
    signal = signal.model_copy(
        update={
            "policy_hash": s.policy.digest,
            "targets": (112, 120, 130),
            "evidence": tuple(
                Evidence(rule=k, outcome="PASS", reason="synthetic", observed_at=NOW)
                for k in requirements(model, "v5")
            ),
        }
    )
    result = size_trade(s, signal, quote, spec, account.model_copy(update={"risk_phase": 3}), NOW)
    assert result.accepted and result.risk_cash <= 500
    missing = signal.model_copy(
        update={"evidence": tuple(e for e in signal.evidence if e.rule != "entry_zone_badge")}
    )
    assert not size_trade(s, missing, quote, spec, account, NOW).accepted


def test_model_requirements_keep_core_smt_optional_and_ers_exception():
    by_name = {x.name: requirements(x, "v5") for x in catalog("v5")}
    assert not {"smt", "q3", "session", "crt_boundary"} & set(by_name["LS"])
    assert "external_qm" in by_name["LS"] and "external_qm" not in by_name["ERS"]
    assert {"early_structure", "storyline_alignment", "entry_zone_badge"} <= set(by_name["ERS"])
    assert all("smt" in by_name[name] for name in ("EX1", "EX3", "QT_SMT", "CIRCLE_FIB"))
    assert "smt" not in by_name["EX2"] and "ema9_hold" in by_name["EX2"]
    assert "m5_badge" in by_name["EX4"]


@pytest.mark.parametrize("direction", [Direction.BUY, Direction.SELL])
def test_rejection_must_use_exact_mapped_frame(direction):
    source = Level("test", "XAUUSDm", "H4", "V", direction, 100, 95, NOW, 0)
    b = candle(0, 101, 103, 99, 102, tf="M15", minutes=15)
    if direction == Direction.SELL:
        b = b.model_copy(update={"open": 99, "high": 101, "low": 97, "close": 98})
    assert MAPPING["H4"] == ("M15",) and MAPPING["H1"] == ("M5",)
    assert mapped_rejection(source, {"M15": [b]}, NOW, b.end)
    assert not mapped_rejection(source, {"H1": [b]}, NOW, b.end)
    assert not mapped_rejection(source, {"M15": [b]}, NOW, b.time)


def test_raw_v5_pipeline_has_no_global_quarter_or_smt_gate():
    s, snap = market_fixture()
    s = s.model_copy(update={"policy": s.policy.model_copy(update={"version": "v5", "minimum_rating": "C"})})
    result = Engine(s).evaluate(snap)
    assert not result.signals  # first fresh opposing level is too close for the required 2R floor
    ls = next(x for x in result.rejected if x.get("setup") == "LS")
    assert ls["rules"] == ["tp1_rr:FAIL"]
    assert "smt:FAIL" not in ls["rules"] and "q3:FAIL" not in ls["rules"]
    snap.bars["M15"] = []
    assert not Engine(s).evaluate(snap).signals


def test_pending_qm_is_not_fabricated_breakout_and_id_stays_stable():
    p = load().policy
    values = [
        (104, 105, 101, 102),
        (102, 106, 101, 105),
        (105, 111, 104, 110),
        (110, 111, 100, 101),
        (101, 102, 94, 95),
        (95, 100, 94, 99),
        (99, 112, 98, 109),
    ]
    bars = [candle(i, *v) for i, v in enumerate(values)]
    q = quasimodos(bars, 0.01, p, pending=True)[0]
    assert q.breakout is None and not qm_valid(q, bars[4].end, "SNR")
    assert not quasimodos(bars, 0.01, p)
    bars.append(candle(7, 109, 113, 108, 112))
    assert quasimodos(bars, 0.01, p)[0].id == q.id
    assert not quasimodos(bars, 0.01, p, pending=True)
    assert not ote(q, 100)


def test_badge_at_other_level_does_not_validate_entry():
    p = load().policy
    b = candle(0, 105, 107, 99, 106, tf="M15", minutes=15)
    assert any(entry_badges({"M15": [b]}, {}, {}, {}, 100, Direction.BUY, NOW, 0.01, p).values())
    assert not any(entry_badges({"M15": [b]}, {}, {}, {}, 95, Direction.BUY, NOW, 0.01, p).values())
    assert not any(entry_badges({"H1": [b]}, {}, {}, {}, 100, Direction.BUY, NOW, 0.01, p).values())


def test_fibonacci_ratios_and_ote_direction():
    assert tuple(fibonacci(100, 200, "v5")) == (
        0.109,
        0.243,
        0.382,
        0.5,
        0.618,
        0.707,
        0.786,
        0.886,
        1.109,
        1.272,
        1.618,
        1.893,
    )
    _, snap = market_fixture()
    q = quasimodos(snap.bars["H1"], 0.01, load().policy)[0]
    price = q.breakout.high - (q.breakout.high - q.apex.apex) * 0.75
    assert ote(q, price) and not ote(q, q.breakout.high)
    sell = replace(q, direction=Direction.SELL, apex=replace(q.apex, apex=120))
    price = sell.breakout.low + (120 - sell.breakout.low) * 0.75
    assert ote(sell, price)


def test_ema_hold_does_not_impose_unlisted_engulfing():
    values = [100] * 10 + [99, 101, 102]
    bars = [candle(i, v - 0.1, v + 0.2, v - 0.2, v) for i, v in enumerate(values)]
    assert ema_badge(bars, Direction.BUY, 1, version="v5")
    assert not ema_badge(bars, Direction.BUY, 1, version="v4")


def test_qt_refuses_imprecise_minute_boundary_data():
    start = datetime(2026, 7, 1, 9, tzinfo=NY)
    bars = [candle(i, 100, 102, 99, 101, tf="M1", minutes=1, start=start) for i in range(60)]
    assert not q2_sweep(bars, start + timedelta(hours=1), Direction.BUY)
