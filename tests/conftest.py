from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from msnr.clock import UTC
from msnr.config import load
from msnr.domain import Bar, Direction, Evidence, Quote, Signal, SymbolSpec, fingerprint
from msnr.risk import Account
from msnr.store import Store
from msnr.strategy.catalog import COMMON

NOW = datetime(2026, 10, 26, 14, 0, tzinfo=UTC)


def candle(i, o, h, low, c, tf="M5", minutes=5, symbol="XAUUSDm", start=NOW):
    return Bar(
        symbol=symbol,
        timeframe=tf,
        time=start + timedelta(minutes=minutes * i),
        end=start + timedelta(minutes=minutes * (i + 1)),
        open=o,
        high=h,
        low=low,
        close=c,
        volume=1,
        source="SYNTHETIC TEST ONLY",
    )


@pytest.fixture
def settings():
    return load()


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


@pytest.fixture
def spec():
    return SymbolSpec(
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


@pytest.fixture
def quote():
    return Quote(symbol="XAUUSDm", time=NOW, bid=100, ask=100.1)


@pytest.fixture
def account():
    return Account(
        id="paper",
        mode="paper",
        at=NOW,
        balance=100000,
        equity=100000,
        free_margin=100000,
        day_start_equity=100000,
        high_water_equity=100000,
        open_risk=0,
        open_positions=0,
        consecutive_daily_losses=0,
        trading_allowed=True,
        reconciled=True,
    )


@pytest.fixture
def signal(settings):
    return Signal(
        id=str(uuid4()),
        fingerprint=fingerprint("synthetic-test-structure"),
        symbol="XAUUSDm",
        direction=Direction.BUY,
        timeframe="M5",
        htf="H1",
        setup="LS",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        entry=100.1,
        stop=95,
        targets=(110, 120, 130),
        rating="A",
        quality_score=50,
        evidence=tuple(
            Evidence(
                rule=rule,
                outcome="PASS",
                reason="Testing execution infrastructure, not market performance",
                observed_at=NOW,
            )
            for rule in COMMON + ("shoulder_entry", "ls_badge", "phase")
        ),
        structure_ids=("fixture",),
        policy_hash=settings.policy.digest,
        reason="Synthetic execution fixture",
        invalidation="Fixture stop",
        data_source="SYNTHETIC TEST ONLY",
    )
