from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator

from .domain import Model, fingerprint


class Instrument(Model):
    symbol: str
    aliases: tuple[str, ...] = ()
    peer: tuple[str, ...] = ()
    inverse_peer: bool | None = False
    stop_buffer: float = Field(gt=0)
    pip_size: float = Field(gt=0)
    max_spread: float = Field(gt=0)
    enabled: bool = True


class Policy(Model):
    version: Literal["v4", "v5"] = "v4"
    authority: str = "User selected v4; see docs/DECISIONS.md"
    body_junction: bool = True
    cc_offset: int = 1
    session_timezone: Literal["America/New_York"] = "America/New_York"
    gap_body_junction: bool | None = None
    max_entry_touch: int | None = None
    mirror_sell_targets: bool | None = None
    partial_original_volume: bool | None = None
    rejection_wick_body_ratio: float | None = Field(default=None, gt=0)
    ema_hold_bars: int | None = Field(default=None, ge=1, le=10)
    alignment_ticks: float | None = Field(default=None, ge=0)
    miss_pips: float | None = Field(default=None, gt=0)
    double_apex_ticks: float | None = Field(default=None, ge=0)
    phase3_profit_fraction: float | None = Field(default=None, gt=0, le=1)
    big_win_r: float | None = Field(default=None, gt=0)
    exhaustion_distance_r: float | None = Field(default=None, gt=0)
    part3_remaining_fraction: float = Field(default=0.2, gt=0, lt=1)
    part3_continuation_breakouts: int = Field(default=2, ge=1)
    cooldown_minutes: int = Field(default=10, ge=1)
    prop_target_fraction: float = Field(default=0.10, gt=0.02, le=0.5)
    phase3_target_distance: float = Field(default=0.02, gt=0, le=0.05)
    advanced_history_complete: bool = False
    # Entry expiration is an operational limit, not a strategy confirmation.
    signal_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    minimum_rating: Literal["A+", "A", "B", "C"] = "B"

    @property
    def digest(self) -> str:
        return fingerprint(self.model_dump())


class RiskLimits(Model):
    evaluation_mode: bool = False
    evaluation_target_fraction: float = Field(default=0.10, gt=0.02, le=0.5)
    per_trade: float = Field(default=0.0033, gt=0, le=0.01)
    daily_loss: float = Field(default=0.02, gt=0, le=0.1)
    max_drawdown: float = Field(default=0.05, gt=0, le=0.3)
    concurrent_risk: float = Field(default=0.01, gt=0, le=0.05)
    max_positions: int = Field(default=3, ge=1, le=20)
    max_slippage_ticks: int = Field(default=5, ge=0, le=100)
    quote_max_age_seconds: int = Field(default=10, ge=1, le=60)
    commission_per_lot: float = Field(default=7.0, ge=0)
    paper_balance: float = Field(default=100000, gt=0)


class Settings(Model):
    schema_version: Literal[1] = 1
    mode: Literal["paper", "backtest", "demo", "live"] = "paper"
    instruments: tuple[Instrument, ...]
    policy: Policy = Field(default_factory=Policy)
    risk: RiskLimits = Field(default_factory=RiskLimits)
    worker_interval_seconds: int = Field(default=5, ge=1, le=60)
    live_authorization_file: str | None = None

    @model_validator(mode="after")
    def unique(self):
        if len({i.symbol for i in self.instruments}) != len(self.instruments):
            raise ValueError("Duplicate instrument")
        return self

    def instrument(self, symbol: str) -> Instrument:
        return next(i for i in self.instruments if i.symbol == symbol and i.enabled)


def load(path: str | Path | None = None) -> Settings:
    return Settings.model_validate_json(
        Path(path or os.getenv("MSNR_CONFIG", "config/default.json")).read_text()
    )


def secret_status() -> dict[str, bool]:
    return {
        name: bool(os.getenv(name))
        for name in ("MSNR_OPERATOR_TOKEN", "MSNR_BRIDGE_URL", "MSNR_BRIDGE_TOKEN", "MSNR_DISCORD_WEBHOOK")
    }


def save(path: Path, settings: Settings) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings.model_dump(), indent=2) + "\n")
    os.replace(temporary, path)
