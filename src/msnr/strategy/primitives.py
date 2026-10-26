from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from ..clock import NY
from ..config import Policy
from ..domain import Bar, Direction, fingerprint


def same_price(a: float, b: float, tick: float) -> bool:
    return abs(a - b) < tick * 1e-6


def round_price(price: float, tick: float, upward: bool) -> float:
    return float(
        (Decimal(str(price)) / Decimal(str(tick))).to_integral_value(
            rounding=ROUND_CEILING if upward else ROUND_FLOOR
        )
        * Decimal(str(tick))
    )


@dataclass(frozen=True)
class Level:
    id: str
    symbol: str
    timeframe: str
    kind: str
    role: Direction
    price: float
    apex: float
    formed: datetime
    index: int
    fresh: bool = True
    repaired: bool = False
    touches: int = 0
    first_touch: datetime | None = None
    last_touch: datetime | None = None
    revision: int = 0
    fresh_before_touch: bool = True


def levels(bars: list[Bar], tick: float, policy: Policy, *, evolve=True) -> list[Level]:
    result = []
    for i in range(1, len(bars)):
        a, b = bars[i - 1 : i + 1]
        if not a.color or not b.color or not same_price(a.close, b.open, tick):
            continue
        if a.color != b.color:
            role = Direction.BUY if b.color > 0 else Direction.SELL
            kind = "V" if role == Direction.BUY else "A"
        elif policy.gap_body_junction is True:
            role = Direction.BUY if b.color > 0 else Direction.SELL
            kind = "GAP_BUY" if role == Direction.BUY else "GAP_SELL"
        else:
            continue
        level = Level(
            fingerprint(b.symbol, b.timeframe, a.time, b.time, kind),
            b.symbol,
            b.timeframe,
            kind,
            role,
            a.close,
            min(a.low, b.low) if role == Direction.BUY else max(a.high, b.high),
            b.end,
            i,
        )
        if evolve:
            contact = False
            for j, c in enumerate(bars[i + 1 :], start=i + 1):
                crossed = c.close < level.price if level.role == Direction.BUY else c.close > level.price
                touching = c.low <= level.price <= c.high
                if crossed:
                    new_role = Direction.SELL if level.role == Direction.BUY else Direction.BUY
                    level = replace(
                        level,
                        kind="SBR" if new_role == Direction.SELL else "RBS",
                        role=new_role,
                        fresh=True,
                        repaired=False,
                        revision=level.revision + 1,
                        formed=c.end,
                        touches=0,
                        first_touch=None,
                        last_touch=None,
                        fresh_before_touch=True,
                    )
                    contact = False
                    continue
                if touching and not contact:
                    level = replace(
                        level,
                        fresh_before_touch=level.fresh,
                        fresh=False,
                        repaired=False,
                        touches=level.touches + 1,
                        first_touch=level.first_touch or c.time,
                        last_touch=c.time,
                    )
                contact = touching
                if (
                    j == i + policy.cc_offset
                    and kind in ("A", "V")
                    and c.color == role.sign
                    and level.revision == 0
                ):
                    level = replace(level, fresh=True, repaired=True)
        result.append(level)
    return result


@dataclass(frozen=True)
class QM:
    id: str
    direction: Direction
    shoulder: Level
    reference: Level
    apex: Level
    breakout: Bar


def quasimodos(bars: list[Bar], tick: float, policy: Policy) -> list[QM]:
    raw = [x for x in levels(bars, tick, policy, evolve=False) if x.kind in ("A", "V")]
    result = []
    for a, b, c in zip(raw, raw[1:], raw[2:]):
        if a.role != c.role or a.role == b.role:
            continue
        d = a.role
        # A sell apex must sweep the first peak; buy must sweep the first trough.
        if (c.apex - a.apex) * d.sign >= 0:
            continue
        for candle in bars[c.index + 1 :]:
            if (candle.close - b.price) * d.sign > 0:
                result.append(QM(fingerprint(a.id, b.id, c.id, candle.end), d, a, b, c, candle))
                break
    return result


def qm_valid(qm: QM, touched_at: datetime, source_kind: str) -> bool:
    external = qm.reference.formed <= touched_at
    post = qm.breakout.end > touched_at if source_kind != "TL" else qm.breakout.end >= touched_at
    return external and post


@dataclass(frozen=True)
class Trendline:
    a: Level
    b: Level
    touches: tuple[datetime, ...]

    def price_at(self, time: datetime) -> float:
        duration = (self.b.formed - self.a.formed).total_seconds()
        return (
            self.a.price + (self.b.price - self.a.price) * (time - self.a.formed).total_seconds() / duration
        )

    @property
    def id(self):
        return fingerprint(self.a.id, self.b.id)


def trendlines(bars: list[Bar], tick: float, policy: Policy) -> list[Trendline]:
    shapes = levels(bars, tick, policy, evolve=False)
    result = []
    for kind in ["A", "V"]:
        anchors = [s for s in shapes if s.kind == kind]
        for a, b in zip(anchors, anchors[1:]):
            if (b.price - a.price) * a.role.sign <= 0:
                continue
            tl = Trendline(a, b, (a.formed, b.formed))
            contacts = list(tl.touches)
            previous = False
            for bar in bars[b.index + 1 :]:
                p = tl.price_at(bar.time)
                touch = bar.low <= p <= bar.high
                if touch and not previous:
                    contacts.append(bar.time)
                previous = touch
            result.append(replace(tl, touches=tuple(contacts)))
    return result


def engulfing(previous: Bar, current: Bar, direction: Direction) -> bool:
    return (
        current.color == direction.sign
        and previous.color == -direction.sign
        and min(current.open, current.close) <= min(previous.open, previous.close)
        and max(current.open, current.close) >= max(previous.open, previous.close)
    )


def rejection(bar: Bar, level: float, direction: Direction, tick: float, ratio: float | None) -> bool | None:
    if ratio is None:
        return None
    wick = (
        min(bar.open, bar.close) - bar.low
        if direction == Direction.BUY
        else bar.high - max(bar.open, bar.close)
    )
    return (
        bar.low <= level <= bar.high
        and bar.color == direction.sign
        and (bar.close - level) * direction.sign > 0
        and wick >= max(tick, abs(bar.close - bar.open) * ratio)
    )


def ema(closes: list[float], length: int = 9) -> list[float | None]:
    if len(closes) < length:
        return [None] * len(closes)
    result = [None] * (length - 1) + [sum(closes[:length]) / length]
    for price in closes[length:]:
        result.append(price * 2 / (length + 1) + result[-1] * (1 - 2 / (length + 1)))
    return result


def ema_badge(bars: list[Bar], direction: Direction, hold_bars: int | None) -> bool | None:
    if hold_bars is None:
        return None
    if len(bars) < 11 + hold_bars or any(b.timeframe != "M5" for b in bars):
        return False
    values = ema([b.close for b in bars])
    cross = len(bars) - hold_bars - 1
    if not engulfing(bars[cross - 1], bars[cross], direction):
        return False
    if (bars[cross - 1].close - values[cross - 1]) * direction.sign > 0:
        return False
    return all((bars[i].close - values[i]) * direction.sign > 0 for i in range(cross, len(bars)))


def crt(previous: Bar, current: Bar) -> str:
    if current.close > previous.high or current.close < previous.low:
        return "expansion"
    if current.high > previous.high or current.low < previous.low:
        return "sweep"
    return "inside"


def ocls(bars: list[Bar], tick: float) -> list[tuple[datetime, float]]:
    return [(b.end, a.close) for a, b in zip(bars, bars[1:]) if same_price(a.close, b.open, tick)]


def smt(primary: list[Level], peer: list[Level], direction: Direction, inverse: bool | None) -> bool | None:
    if inverse is None:
        return None
    primary = [p for p in primary if p.role == direction and p.kind in ("A", "V")]
    peer_role = Direction.SELL if direction == Direction.BUY else Direction.BUY
    peer = [p for p in peer if p.role == (peer_role if inverse else direction) and p.kind in ("A", "V")]
    if len(primary) < 2 or len(peer) < 2:
        return None
    a, b = primary[-2:]
    c, d = peer[-2:]
    # Exact interval alignment prevents comparing unrelated historical swings.
    if a.formed != c.formed or b.formed != d.formed:
        return None
    movement = (b.apex - a.apex) * direction.sign
    other = (d.apex - c.apex) * (peer_role.sign if inverse else direction.sign)
    return movement < 0 and other > 0


def asia_range(bars: list[Bar], now: datetime) -> tuple[float, float] | None:
    local = now.astimezone(NY)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(hours=5)
    selected = [b for b in bars if b.time >= start and b.end <= midnight]
    if not selected or selected[0].time != start or selected[-1].end != midnight:
        return None
    if any(a.end != b.time for a, b in zip(selected, selected[1:])):
        return None
    return min(b.low for b in selected), max(b.high for b in selected)


FIBO_RATIOS = (0.0, 0.109, 0.25, 0.50, 0.707, 0.886, 1.0, 1.272, 1.618, 1.893, 2.0)


def fibonacci(low: float, high: float) -> dict[float, float]:
    if high <= low:
        raise ValueError("Fibonacci requires ordered confirmed swing anchors")
    return {r: low + (high - low) * r for r in FIBO_RATIOS}


def trendline_break(bars: list[Bar], lines: list[Trendline], direction: Direction, after: datetime):
    matches = []
    for a, b in zip(bars, bars[1:]):
        if b.end <= after or not engulfing(a, b, direction):
            continue
        for line in lines:
            if line.b.formed > a.time:
                continue
            if (
                (a.close - line.price_at(a.end)) * direction.sign
                <= 0
                < (b.close - line.price_at(b.end)) * direction.sign
            ):
                matches.append((line, b, line.price_at(b.end)))
    return matches


def inducement_sweep(
    bars: list[Bar], shapes: list[Level], direction: Direction, poi: float, tolerance: float, after: datetime
) -> bool:
    for b in bars:
        if b.time < after or not b.low - tolerance <= poi <= b.high + tolerance:
            continue
        references = [
            s for s in shapes if s.role == direction and s.formed <= b.time and s.kind in ("A", "V")
        ]
        if references:
            level = references[-1].apex
            if (
                direction == Direction.BUY
                and b.low < level < b.close
                or direction == Direction.SELL
                and b.high > level > b.close
            ):
                return True
    return False


def failed_qm_reversal(bars: list[Bar], tick: float, policy: Policy, direction: Direction) -> bool:
    shapes = [s for s in levels(bars, tick, policy, evolve=False) if s.kind in ("A", "V")]
    for a, b, c in zip(shapes, shapes[1:], shapes[2:]):
        if (
            a.role == direction
            or a.role != c.role
            or a.role == b.role
            or (c.apex - a.apex) * a.role.sign >= 0
        ):
            continue
        subsequent = bars[c.index + 1 :]
        for previous, current in zip(subsequent, subsequent[1:]):
            if any((x.close - b.price) * a.role.sign > 0 for x in subsequent if x.end <= current.end):
                break  # This was a successful QM, so do not relabel it a failed pattern.
            if (previous.close - a.price) * direction.sign <= 0 < (current.close - a.price) * direction.sign:
                return True
    return False
