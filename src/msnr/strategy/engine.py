from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from ..clock import quarter, session
from ..config import Settings
from ..data import series
from ..domain import Bar, Direction, Evidence, Quote, Signal, SymbolSpec, fingerprint
from .catalog import CATALOG, COMMON, RATING_ORDER, rating
from .primitives import (
    Level,
    QM,
    asia_range,
    crt,
    ema_badge,
    engulfing,
    levels,
    ocls,
    qm_valid,
    quasimodos,
    rejection,
    round_price,
    smt,
    trendlines,
)
from .primitives import trendline_break, inducement_sweep, failed_qm_reversal

MAPPING = {
    "MN1": ("D1",),
    "W1": ("H4",),
    "D1": ("H1",),
    "H4": ("H1", "M30", "M15"),
    "H1": ("M30", "M15"),
    "M30": ("M5",),
    "M15": ("M1",),
}


@dataclass
class Snapshot:
    now: datetime
    symbol: str
    bars: dict[str, list[Bar]]
    spec: SymbolSpec
    quote: Quote
    peers: dict[str, dict[str, list[Bar]]] = field(default_factory=dict)
    peer_specs: dict[str, SymbolSpec] = field(default_factory=dict)
    # Only current-instance observed partial candles, timestamped when retrieved.
    partial_htf: dict[str, Bar] = field(default_factory=dict)


@dataclass
class Evaluation:
    signals: list[Signal] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    structures: dict = field(default_factory=dict)


def gate(
    facts: dict[str, bool | None], required: tuple[str, ...], now: datetime, source_ids=()
) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(
            rule=key,
            outcome="UNKNOWN" if facts.get(key) is None else "PASS" if facts[key] else "FAIL",
            reason=(
                "Required evidence verified"
                if facts.get(key) is True
                else "Required evidence absent or not satisfied"
            ),
            observed_at=now,
            source_ids=source_ids,
        )
        for key in required
    )


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.policy = settings.policy

    def evaluate(self, snap: Snapshot) -> Evaluation:
        out = Evaluation()
        if snap.quote.symbol != snap.symbol or snap.spec.symbol != snap.symbol:
            raise ValueError("Snapshot symbol isolation violated")
        age = (snap.now - snap.quote.time).total_seconds()
        if age < 0 or age > self.settings.risk.quote_max_age_seconds:
            out.rejected.append({"reason": "stale_or_future_quote"})
            return out
        bars = {tf: series(bs, snap.now, symbol=snap.symbol, timeframe=tf) for tf, bs in snap.bars.items()}
        if not bars or any(not bs for bs in bars.values()):
            out.rejected.append({"reason": "missing_closed_bars"})
            return out
        tick = snap.spec.tick_size
        level_map = {tf: levels(bs, tick, self.policy) for tf, bs in bars.items()}
        qm_map = {tf: quasimodos(bs, tick, self.policy) for tf, bs in bars.items()}
        tl_map = {tf: trendlines(bs, tick, self.policy) for tf, bs in bars.items()}
        out.structures = {
            tf: {"levels": len(ls), "qm": len(qm_map[tf]), "trendlines": len(tl_map[tf])}
            for tf, ls in level_map.items()
        }
        seen = set()
        for htf, ltfs in MAPPING.items():
            if htf not in bars:
                continue
            for source in level_map[htf]:
                if source.kind not in ("A", "V", "GAP_BUY", "GAP_SELL", "SBR", "RBS"):
                    continue
                for ltf in ltfs:
                    if ltf not in bars:
                        continue
                    for qm in qm_map[ltf][-8:]:
                        if qm.direction != source.role or qm.breakout.end < source.formed:
                            continue
                        key = (source.id, source.revision, qm.id)
                        if key in seen:
                            continue
                        seen.add(key)
                        self._candidate(snap, bars, level_map, qm_map, tl_map, source, qm, htf, ltf, out)
            if self.policy.advanced_history_complete and not any(x.fresh for x in level_map[htf]):
                for line in tl_map[htf]:
                    if (
                        self.policy.max_entry_touch is None
                        or not 3 <= len(line.touches) <= self.policy.max_entry_touch
                    ):
                        continue
                    source = Level(
                        line.id,
                        snap.symbol,
                        htf,
                        "TL",
                        line.a.role,
                        line.price_at(snap.now),
                        line.b.apex,
                        line.b.formed,
                        line.b.index,
                        touches=len(line.touches),
                    )
                    for ltf in ltfs:
                        for qm in qm_map.get(ltf, [])[-8:]:
                            if qm.direction == source.role and qm.breakout.end >= source.formed:
                                seen.add((line.id, qm.id))
                                self._candidate(
                                    snap, bars, level_map, qm_map, tl_map, source, qm, htf, ltf, out, line
                                )
        if not seen:
            out.rejected.append({"reason": "No observable external QM aligned with an HTF source"})
        # Advanced storyline cannot assert that all historical levels are exhausted from a finite sample.
        if not self.policy.advanced_history_complete:
            out.rejected.append(
                {
                    "setup": "ADVANCED_STORYLINE",
                    "reason": "Complete level-history coverage has not been attested",
                }
            )
        return out

    def _candidate(self, snap, bars, lm, qm_map, tl_map, source: Level, qm: QM, htf, ltf, out, line=None):
        direction = qm.direction
        sign = direction.sign
        tick = snap.spec.tick_size
        instrument = self.settings.instrument(snap.symbol)
        tolerance = (self.policy.alignment_ticks or 0) * tick
        micro = bars.get("M1") or bars.get("M5") or bars[ltf]
        confirmation_window = [b for b in micro if b.end >= qm.apex.formed]
        if any(a.end != b.time for a, b in zip(confirmation_window, confirmation_window[1:])):
            out.rejected.append(
                {"setup": "ALL", "reason": "Missing lower-timeframe bars in confirmation window"}
            )
            return
        touch_bars = [
            b
            for b in micro
            if b.time >= source.formed
            and b.low <= (line.price_at(b.time) if line else source.price) <= b.high
        ]
        if not touch_bars:
            return
        # Group contiguous contact into a single touch episode; last episode governs breakout ordering.
        episodes = []
        for b in touch_bars:
            if not episodes or episodes[-1][-1].end != b.time:
                episodes.append([b])
            else:
                episodes[-1].append(b)
        touch = episodes[-1][-1].end
        prior_touches = len(episodes) - 1
        source_current_touch = any(
            b.time == source.last_touch and b.time <= touch <= b.end for b in bars[htf]
        )
        fresh = (
            (3 <= len(line.touches) <= self.policy.max_entry_touch)
            if line
            else (source.fresh or source_current_touch and source.fresh_before_touch)
            and (prior_touches == 0 or source.repaired)
        )
        htf_rejection_bar = bars[htf][-1]
        if htf in ("W1", "MN1") and htf in snap.partial_htf:
            partial = snap.partial_htf[htf]
            if partial.end > snap.now or partial.symbol != snap.symbol:
                raise ValueError("Future/mixed partial HTF bar")
            htf_rejection_bar = partial
        rejection_ok = rejection(
            htf_rejection_bar,
            line.price_at(htf_rejection_bar.time) if line else source.price,
            direction,
            tick,
            self.policy.rejection_wick_body_ratio,
        )
        if htf in ("W1", "MN1"):
            boundary = line.price_at(htf_rejection_bar.time) if line else source.price
            rejection_ok = (
                htf_rejection_bar.low <= boundary < min(htf_rejection_bar.open, htf_rejection_bar.close)
                if direction == Direction.BUY
                else max(htf_rejection_bar.open, htf_rejection_bar.close) < boundary <= htf_rejection_bar.high
            )
        elif htf == "H1" and rejection_ok is not True and bars.get("H4"):
            rejection_ok = rejection(
                bars["H4"][-1], source.price, direction, tick, self.policy.rejection_wick_body_ratio
            )
        badges = {}
        for tf in ("M5", "M15", "M30", "H1"):
            if bars.get(tf):
                b = bars[tf][-1]
                badges["rejection_" + tf] = b.end >= touch and rejection(
                    b, qm.shoulder.price, direction, tick, self.policy.rejection_wick_body_ratio
                )
        badges["ema9"] = ema_badge(bars.get("M5", []), direction, self.policy.ema_hold_bars)
        if bars.get("M5") and bars["M5"][-1].end < touch:
            badges["ema9"] = False
        badges["mini_qm"] = any(
            q.direction == direction
            and q.breakout.end >= touch
            and abs(q.shoulder.price - qm.shoulder.price) <= tolerance
            for tf in ("M1", "M5")
            for q in qm_map.get(tf, [])[-3:]
        )
        gap_break = False
        tl_break = False
        for tf in ("M5", "M15"):
            bs = bars.get(tf, [])
            if len(bs) >= 2 and engulfing(bs[-2], bs[-1], direction):
                gap_break |= any(
                    x.kind.startswith("GAP")
                    and x.formed < bs[-1].time
                    and (bs[-2].close - x.price) * sign <= 0 < (bs[-1].close - x.price) * sign
                    for x in lm.get(tf, [])
                )
        for tf in ("M1", "M5"):
            bs = bars.get(tf, [])
            if len(bs) >= 2 and engulfing(bs[-2], bs[-1], direction):
                tl_break |= any(
                    (bs[-2].close - t.price_at(bs[-2].end)) * sign
                    <= 0
                    < (bs[-1].close - t.price_at(bs[-1].end)) * sign
                    for t in tl_map.get(tf, [])
                    if t.b.formed < bs[-2].time
                )
        badges.update(gap_break=gap_break, tl_break=tl_break)
        badge = any(v is True for v in badges.values())
        last = micro[-1]

        def near(p):
            return last.low - tolerance <= p <= last.high + tolerance

        after_break = last.time >= qm.breakout.end
        flipped = [
            x
            for tf in (ltf, "M5", "H1")
            for x in lm.get(tf, [])
            if x.kind in ("SBR", "RBS") and x.role == direction
        ]
        gaps = [
            x
            for tf in (ltf, "H1", "H4")
            for x in lm.get(tf, [])
            if x.kind.startswith("GAP") and x.role == direction
        ]
        ers = [
            x
            for x in lm[ltf]
            if x.role == direction and qm.apex.formed < x.formed < qm.breakout.end and x.kind in ("A", "V")
        ]
        active_tl = [
            t
            for tf in ("M1", "M5", ltf)
            for t in tl_map.get(tf, [])
            if t.a.role == direction
            and self.policy.max_entry_touch is not None
            and 3 <= len(t.touches) <= self.policy.max_entry_touch
            and abs(t.price_at(last.time) - qm.shoulder.price) <= tolerance
        ]
        smt_result = None
        for peer_name in instrument.peer:
            peer_bars = snap.peers.get(peer_name, {}).get(ltf, [])
            peer_spec = snap.peer_specs.get(peer_name)
            if peer_bars and peer_spec:
                smt_result = smt(
                    levels(bars[ltf], tick, self.policy, evolve=False),
                    levels(
                        series(peer_bars, snap.now, symbol=peer_name, timeframe=ltf),
                        peer_spec.tick_size,
                        self.policy,
                        evolve=False,
                    ),
                    direction,
                    instrument.inverse_peer,
                )
                break
        ar = asia_range(bars.get("M5", []), snap.now)
        sweep_bars = (
            []
            if ar is None
            else [
                b
                for b in bars.get("M5", [])
                if b.time >= source.formed
                and b.low - tolerance <= source.price <= b.high + tolerance
                and session(b.end) in ("london", "new_york_am", "new_york_pm")
                and ((b.low < ar[0] < b.close) if sign == 1 else (b.high > ar[1] > b.close))
            ]
        )
        asia_sweep = None if ar is None else bool(sweep_bars)
        session_ok = session(snap.now) in ("london", "new_york_am", "new_york_pm")
        q3 = quarter(snap.now) == 3
        entry = snap.quote.ask if sign == 1 else snap.quote.bid
        stop = round_price(qm.apex.apex - sign * instrument.stop_buffer, tick, upward=sign == -1)
        targets = self._targets(lm, entry, direction)
        if line and len(targets) < 3:
            target_map = {tf: list(values) for tf, values in lm.items()}
            for tf in ("D1", "W1", "MN1"):
                target_map.setdefault(tf, [])
                for target_line in tl_map.get(tf, []):
                    if target_line.a.role != direction and len(target_line.touches) < 5:
                        target_map[tf].append(
                            Level(
                                target_line.id,
                                snap.symbol,
                                tf,
                                "TL",
                                target_line.a.role,
                                target_line.price_at(snap.now),
                                target_line.b.apex,
                                target_line.b.formed,
                                target_line.b.index,
                            )
                        )
            targets = self._targets(target_map, entry, direction)
        other_qms = [q for q in qm_map[ltf] if q.direction == direction and q.breakout.end < qm.breakout.end]
        continuation = bool(other_qms and (qm.apex.apex - other_qms[-1].apex.apex) * sign > 0)
        phase = 2 if continuation else 1
        if phase == 2 and targets:
            total = (targets[-1] - source.price) * sign
            remaining = (targets[-1] - entry) * sign
            continuation_count = (
                sum(1 for a, b in zip(other_qms, other_qms[1:]) if (b.apex.apex - a.apex.apex) * sign > 0) + 1
            )
            if (
                total > 0
                and remaining / total <= self.policy.part3_remaining_fraction
                or continuation_count >= self.policy.part3_continuation_breakouts
            ):
                phase = 3
        raw_shapes = levels(bars[ltf], tick, self.policy, evolve=False)
        double = [
            s for s in raw_shapes if s.role == direction and s.id != qm.apex.id and s.formed < qm.breakout.end
        ]
        double_apex = (
            None
            if self.policy.double_apex_ticks is None
            else any(abs(s.apex - qm.apex.apex) <= self.policy.double_apex_ticks * tick for s in double[-3:])
        )
        facts = {
            "source_valid": fresh,
            "htf_rejection": rejection_ok,
            "external_qm": qm_valid(qm, touch, "TL" if line else "SNR"),
            "mtf_mapping": ltf in MAPPING[htf],
            "badge": badge,
            "entry_retest": after_break,
            "targets": len(targets) == 3,
            "stop_buffer": (entry - stop) * sign > 0,
            "apex_entry": near(qm.apex.apex),
            "shoulder_entry": near(qm.shoulder.price),
            "ls_badge": badges.get("rejection_M15") is True
            or badges.get("rejection_M5") is True
            or badges.get("ema9") is True,
            "flip_entry": any(near(x.price) and (x.fresh or x.fresh_before_touch) for x in flipped),
            "flip_badge": gap_break or tl_break,
            "ers_entry": any(near(x.price) for x in ers),
            "tl_alignment": bool(active_tl),
            "gap_entry": any(near(x.price) and x.fresh for x in gaps),
            "continuation": continuation,
            "nested_qm": badges["mini_qm"],
            "miss_entry": None
            if self.policy.miss_pips is None
            else 0
            < min(abs(last.low - qm.shoulder.price), abs(last.high - qm.shoulder.price))
            <= instrument.pip_size * self.policy.miss_pips,
            "ers_or_ocl": any(near(x.price) for x in ers) or any(near(p) for _, p in ocls(micro, tick)),
            "double_apex": double_apex,
            "fresh_av": source.kind in ("A", "V") and fresh,
            "third_touch": any(len(t.touches) == 3 for t in active_tl),
            "h1_ocl": any(near(p) for _, p in ocls(bars.get("H1", []), tick)),
            "h1_flip": any(near(x.price) for x in lm.get("H1", []) if x.kind in ("SBR", "RBS")),
            "micro_ocl_retest": after_break and any(near(p) for _, p in ocls(micro, tick)),
            "m15_shift": any(
                q.direction == direction and q.breakout.end > touch for q in qm_map.get("M15", [])[-3:]
            ),
            "m3_shift": any(
                q.direction == direction and q.breakout.end > touch for q in qm_map.get("M3", [])[-3:]
            ),
            "m5_shift": any(
                q.direction == direction and q.breakout.end > touch for q in qm_map.get("M5", [])[-3:]
            ),
            "q3": q3,
            "smt": smt_result,
            "asia_sweep": asia_sweep,
            "h1_poi": htf == "H1",
            "session": session_ok,
            "crt_boundary": len(bars[htf]) >= 2 and crt(bars[htf][-2], htf_rejection_bar) != "inside",
            "inducement": inducement_sweep(
                bars.get("M3", []),
                levels(bars.get("M3", []), tick, self.policy, evolve=False),
                direction,
                source.price,
                tolerance,
                source.formed,
            ),
            "h1_tl_key": any(
                abs(key - source.price) <= tolerance
                for _, _, key in trendline_break(
                    bars.get("H1", []), tl_map.get("H1", []), direction, source.formed
                )
            ),
            "m3_tl_break": bool(trendline_break(bars.get("M3", []), tl_map.get("M3", []), direction, touch)),
            "failed_qm": failed_qm_reversal(bars[ltf], tick, self.policy, direction),
        }
        facts["apex_refinement"] = all(
            any(
                x.role == direction and (x.fresh or x.repaired) and abs(x.price - qm.apex.apex) <= tolerance
                for x in lm.get(tf, [])
            )
            for tf in ("H4", "H1", "M30", "M15")
        )
        facts["gap_alignment"] = all(
            any(x.kind.startswith("GAP") and abs(x.price - source.price) <= tolerance for x in lm.get(tf, []))
            for tf in ("H4", "H1")
        ) and any(
            x.kind in ("A", "V") and abs(x.price - source.price) <= tolerance
            for tf in ("M30", "M15")
            for x in lm.get(tf, [])
        )
        optional = {
            "smt": smt_result,
            "third_touch": facts["third_touch"],
            "mtf_alignment": all(
                any(x.role == direction and abs(x.price - source.price) <= tolerance for x in lm.get(tf, []))
                for tf in ("MN1", "W1", "D1")
            ),
            "multiple_badges": sum(v is True for v in badges.values()) >= 2,
        }
        grade, score, confluences = rating(optional)
        for model in CATALOG:
            required = COMMON + model.requirements + ("phase",) + (("session",) if model.hybrid else ())
            model_facts = {**facts, "phase": phase in model.phases}
            evidence = gate(model_facts, required, snap.now, (source.id, qm.id))
            failures = [e.rule + ":" + e.outcome for e in evidence if e.outcome != "PASS"]
            if RATING_ORDER[grade] < RATING_ORDER[self.policy.minimum_rating]:
                failures.append("rating_below_configured_threshold")
            if failures:
                out.rejected.append({"setup": model.name, "htf": htf, "timeframe": ltf, "rules": failures})
                continue
            fp = fingerprint(
                snap.symbol,
                direction,
                htf,
                ltf,
                model.name,
                source.id,
                source.revision,
                qm.id,
                self.policy.digest,
            )
            out.signals.append(
                Signal(
                    id=str(uuid4()),
                    fingerprint=fp,
                    symbol=snap.symbol,
                    direction=direction,
                    timeframe=ltf,
                    htf=htf,
                    setup=model.name,
                    created_at=snap.now,
                    expires_at=snap.now + timedelta(seconds=self.policy.signal_ttl_seconds),
                    entry=entry,
                    stop=stop,
                    targets=tuple(targets),
                    rating=grade,
                    quality_score=score,
                    evidence=evidence,
                    structure_ids=(source.id, qm.id),
                    policy_hash=self.policy.digest,
                    reason=f"{htf} {source.kind} → {ltf} external QM; badges: "
                    + ", ".join(k for k, v in badges.items() if v is True)
                    + "; optional confluence: "
                    + ", ".join(confluences),
                    invalidation="Expire at the recorded deadline; invalidate before entry on a closed structural break through the stop extreme or contrary storyline.",
                    data_source=last.source,
                    chart_features=(
                        {
                            "label": htf + " " + source.kind,
                            "time": source.formed.isoformat(),
                            "price": source.price,
                        },
                        {
                            "label": "Left shoulder",
                            "time": qm.shoulder.formed.isoformat(),
                            "price": qm.shoulder.price,
                        },
                        {
                            "label": "External reference",
                            "time": qm.reference.formed.isoformat(),
                            "price": qm.reference.price,
                        },
                        {"label": "Apex / sweep", "time": qm.apex.formed.isoformat(), "price": qm.apex.apex},
                        {
                            "label": "Body breakout",
                            "time": qm.breakout.end.isoformat(),
                            "price": qm.breakout.close,
                        },
                    ),
                )
            )

    def _targets(self, lm, entry, direction):
        if direction == Direction.SELL and self.policy.mirror_sell_targets is not True:
            return []
        sign = direction.sign
        targets = []
        after = entry
        for frames, types in [
            (("H1", "H4"), ("SBR", "RBS", "GAP_BUY", "GAP_SELL")),
            (("D1",), None),
            (("W1", "MN1"), None),
        ]:
            candidates = [
                x.price
                for tf in frames
                for x in lm.get(tf, [])
                if x.role != direction
                and x.fresh
                and (x.price - after) * sign > 0
                and (types is None or x.kind in types)
            ]
            if not candidates:
                return []
            after = min(candidates) if sign == 1 else max(candidates)
            targets.append(after)
        return targets
