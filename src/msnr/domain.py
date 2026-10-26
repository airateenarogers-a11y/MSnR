from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

from .clock import aware


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self == Direction.BUY else -1


class Bar(Model):
    symbol: str
    timeframe: str
    time: datetime
    end: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(default=0, ge=0)
    source: str = "unknown"

    @field_validator("time", "end")
    @classmethod
    def timestamps(cls, v: datetime) -> datetime:
        return aware(v)

    @model_validator(mode="after")
    def valid(self):
        if (
            self.end <= self.time
            or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high
        ):
            raise ValueError("Invalid candle chronology or OHLC geometry")
        return self

    @property
    def color(self) -> int:
        return (self.close > self.open) - (self.close < self.open)


class Quote(Model):
    symbol: str
    time: datetime
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)

    @field_validator("time")
    @classmethod
    def timestamp(cls, v):
        return aware(v)

    @model_validator(mode="after")
    def valid(self):
        if self.ask < self.bid:
            raise ValueError("Crossed quote")
        return self


class SymbolSpec(Model):
    symbol: str
    tick_size: float = Field(gt=0)
    tick_value_loss: float = Field(gt=0)
    point: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    stops_distance: float = Field(ge=0)
    freeze_distance: float = Field(default=0, ge=0)
    contract_size: float = Field(gt=0)
    trade_allowed: bool
    market_open: bool
    currency_profit: str
    currency_account: str
    filling_modes: tuple[str, ...] = ("IOC",)

    @model_validator(mode="after")
    def valid(self):
        if self.volume_max < self.volume_min:
            raise ValueError("Invalid broker volume limits")
        return self


class Evidence(Model):
    rule: str
    outcome: Literal["PASS", "FAIL", "UNKNOWN"]
    reason: str
    observed_at: datetime
    source_ids: tuple[str, ...] = ()
    values: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def timestamp(cls, v):
        return aware(v)


class Signal(Model):
    id: str
    fingerprint: str
    symbol: str
    direction: Direction
    timeframe: str
    htf: str
    setup: str
    created_at: datetime
    expires_at: datetime
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    targets: tuple[float, ...]
    rating: Literal["A+", "A", "B", "C"]
    quality_score: int = Field(ge=0, le=100)
    evidence: tuple[Evidence, ...]
    structure_ids: tuple[str, ...]
    policy_hash: str
    reason: str
    invalidation: str
    data_source: str
    chart_features: tuple[dict[str, Any], ...] = ()

    @field_validator("created_at", "expires_at")
    @classmethod
    def timestamps(cls, v):
        return aware(v)

    @model_validator(mode="after")
    def valid(self):
        s = self.direction.sign
        if (self.entry - self.stop) * s <= 0 or len(self.targets) != 3:
            raise ValueError("Stop must be adverse and three targets are required")
        if any((b - a) * s <= 0 for a, b in zip((self.entry,) + self.targets, self.targets)):
            raise ValueError("Targets must be ordered beyond entry")
        if self.expires_at <= self.created_at:
            raise ValueError("Signal must have a future expiry")
        if not self.evidence or any(e.outcome != "PASS" for e in self.evidence):
            raise ValueError("Every mandatory evidence item must pass")
        if any(e.observed_at > self.created_at for e in self.evidence):
            raise ValueError("Future evidence is prohibited")
        return self

    @property
    def rr(self) -> tuple[float, ...]:
        return tuple(abs(t - self.entry) / abs(self.entry - self.stop) for t in self.targets)


def fingerprint(*parts: Any) -> str:
    return sha256(json.dumps(parts, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
