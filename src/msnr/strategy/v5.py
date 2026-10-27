"""V5 predicates. All inputs are observed, closed, symbol-isolated candles."""

from datetime import timedelta

from ..clock import NY, quarter
from ..domain import Direction
from .primitives import ema_badge, rejection, asia_range

MAPPING = {"MN1": ("D1",), "W1": ("H4",), "D1": ("H1",), "H4": ("M15",), "H1": ("M5",)}


def mapped_rejection(source, bars, after, before, line=None):
    """Validate the source on its specified frame, without requiring a future HTF close."""
    frame = MAPPING.get(source.timeframe, ())
    if not frame:
        return False
    for b in bars.get(frame[0], []):
        if b.end < after or b.end > before or b.time < source.formed:
            continue
        boundary = line.price_at(b.time) if line else source.price
        wick = (
            b.low <= boundary < min(b.open, b.close)
            if source.role == Direction.BUY
            else max(b.open, b.close) < boundary <= b.high
        )
        body = b.low <= boundary <= b.high and (b.close - boundary) * source.role.sign > 0
        if wick if source.timeframe in ("MN1", "W1") else body:
            return True
    return False


def entry_badges(bars, lm, qms, tls, boundary, direction, after, tick, policy, frames=None):
    tol = (policy.alignment_ticks or 0) * tick
    sign = direction.sign
    result = {}
    for tf in frames or ("M5", "M15"):
        bs = bars.get(tf, [])
        if not bs:
            continue
        b = bs[-1]
        # A badge must occur at the actual entry level, not a different model's shoulder.
        at_zone = b.end >= after and b.low - tol <= boundary <= b.high + tol
        result["rejection_" + tf] = at_zone and rejection(
            b, boundary, direction, tick, policy.rejection_wick_body_ratio
        )
        if len(bs) > 1:
            a = bs[-2]
            result["gap_break_" + tf] = at_zone and any(
                x.kind.startswith("GAP")
                and x.formed <= a.time
                and (a.close - x.price) * sign <= 0 < (b.close - x.price) * sign
                for x in lm.get(tf, [])
            )
            result["tl_break_" + tf] = at_zone and any(
                t.b.formed <= a.time
                and (a.close - t.price_at(a.end)) * sign <= 0 < (b.close - t.price_at(b.end)) * sign
                for t in tls.get(tf, [])
            )
    m5 = bars.get("M5", [])
    result["ema9"] = bool(
        len(m5) >= 3
        and m5[-2].time >= after
        and any(b.low - tol <= boundary <= b.high + tol for b in m5[-2:])
        and ema_badge(m5, direction, policy.ema_hold_bars, version="v5")
    )
    result["mini_qm"] = any(
        q.direction == direction and q.breakout.end >= after and abs(q.shoulder.price - boundary) <= tol
        for tf in (("M5",) if frames else ("M1", "M5"))
        for q in qms.get(tf, [])[-3:]
    )
    return result


def session_sweep(bars, now, direction, boundary, tolerance, after):
    ranges = []
    asia = asia_range(bars, now, "v5")
    local = now.astimezone(NY)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if asia:
        ranges.append((*asia, midnight))
    start, end = midnight + timedelta(hours=2), midnight + timedelta(hours=5)
    london = [b for b in bars if start <= b.time and b.end <= end]
    if (
        now >= end
        and london
        and london[0].time == start
        and london[-1].end == end
        and all(a.end == b.time for a, b in zip(london, london[1:]))
    ):
        ranges.append((min(b.low for b in london), max(b.high for b in london), end))
    return any(
        b.time >= max(after, end)
        and b.low - tolerance <= boundary <= b.high + tolerance
        and (b.low < low < b.close if direction == Direction.BUY else b.high > high > b.close)
        for low, high, end in ranges
        for b in bars
    )


def ote(qm, price):
    if qm.breakout is None:
        return False
    if qm.direction == Direction.BUY:
        low, high = qm.apex.apex, qm.breakout.high
        return high > low and high - (high - low) * 0.786 <= price <= high - (high - low) * 0.707
    low, high = qm.breakout.low, qm.apex.apex
    return high > low and low + (high - low) * 0.707 <= price <= low + (high - low) * 0.786


def q2_sweep(bars, now, direction):
    local = now.astimezone(NY)
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        seconds=seconds // 5400 * 5400
    )
    # M1 cannot describe the exact 22.5-minute boundary. Require complete sub-minute evidence.
    q1_end = start + timedelta(seconds=1350)
    first = [b for b in bars if start <= b.time and b.end <= q1_end]
    if (
        not first
        or first[0].time != start
        or first[-1].end != q1_end
        or any(a.end != b.time for a, b in zip(first, first[1:]))
    ):
        return False
    low, high = min(b.low for b in first), max(b.high for b in first)
    return any(
        b.time >= q1_end
        and b.end <= start + timedelta(seconds=2700)
        and quarter(b.time, "v5") == 2
        and (b.low < low < b.close if direction == Direction.BUY else b.high > high > b.close)
        for b in bars
    )
