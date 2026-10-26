from __future__ import annotations

import calendar
import csv
from datetime import datetime, timedelta
from pathlib import Path

from .clock import UTC, aware
from .domain import Bar

MINUTES = {"M1": 1, "M3": 3, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080}
TIMEFRAMES = (*MINUTES, "MN1")


def end_time(start: datetime, timeframe: str) -> datetime:
    start = aware(start)
    if timeframe == "MN1":
        return start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1, day=1)
    return start + timedelta(minutes=MINUTES[timeframe])


def series(bars: list[Bar], now: datetime, *, symbol=None, timeframe=None) -> list[Bar]:
    now = aware(now)
    selected = [b for b in bars if b.end <= now]
    for i, b in enumerate(selected):
        if symbol and b.symbol != symbol or timeframe and b.timeframe != timeframe:
            raise ValueError("Mixed symbol/timeframe data")
        if i and (
            b.time <= selected[i - 1].time
            or b.symbol != selected[i - 1].symbol
            or b.timeframe != selected[i - 1].timeframe
            or b.source != selected[i - 1].source
        ):
            raise ValueError("Non-increasing, mixed-source or duplicate bars")
    return selected


def read_csv(path: Path, symbol: str, timeframe: str, source: str) -> list[Bar]:
    if not source or source == "unknown":
        raise ValueError("A truthful data source label is required")
    with path.open(newline="") as f:
        result = []
        for row in csv.DictReader(f):
            start = aware(datetime.fromisoformat(row["time"]))
            result.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    time=start,
                    end=aware(datetime.fromisoformat(row["end"]))
                    if row.get("end")
                    else end_time(start, timeframe),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0),
                    source=source,
                )
            )
    series(result, datetime.max.replace(tzinfo=UTC), symbol=symbol, timeframe=timeframe)
    return result


def aggregate_observed(
    bars: list[Bar], start: datetime, end: datetime, now: datetime, timeframe: str
) -> Bar | None:
    """Partial HTF OHLC from already closed lower bars only; no final-bar leakage."""
    selected = [b for b in bars if start <= b.time and b.end <= min(aware(now), end)]
    if not selected or selected[0].time != start:
        return None
    if any(a.end != b.time for a, b in zip(selected, selected[1:])):
        return None
    return Bar(
        symbol=selected[0].symbol,
        timeframe=timeframe,
        time=start,
        end=selected[-1].end,
        open=selected[0].open,
        high=max(b.high for b in selected),
        low=min(b.low for b in selected),
        close=selected[-1].close,
        volume=sum(b.volume for b in selected),
        source=selected[0].source,
    )


def month_days(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
