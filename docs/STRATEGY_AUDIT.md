# Strategy audit — before implementation

Both supplied Markdown guides have been read in full (v3: 626 lines; v4: 712 lines). They are preserved byte-for-byte in `sources/`. The PDF is supplementary source material, not permission to override the Markdown. Claims about author performance, institutional intent, probabilities, and a "10/10" setup are assertions in the source, not verified performance measurements.

## Authority and fail-closed contract

The user selected v4 as authoritative and supplied mechanical clarifications in `DECISIONS.md`. V3 is retained only to expose historical conflicts. The ambiguity table below records the initial audit; the decision log records their current resolution. A strategy policy must name its version, approval reference, and resolved mechanical definitions before it can generate eligible signals. Missing or contradictory evidence has outcome UNKNOWN or FAIL, never PASS. Every setup is evaluated against common requirements AND its model-specific requirements. Scores cannot bypass a gate. Test policies are explicitly synthetic fixtures, not production approvals.

## Material ambiguities and conflicts

| ID | Source | Issue | Required decision / execution consequence |
|---|---|---|---|
| A01 | v3/v4 | Versions disagree on internal breakouts, GAP, EX2–4, Fibonacci, risk, loss/cooldown rules | Select authoritative version; no silent merge. |
| A02 | v4 3.1–3.2 | "peak body/wick high" / "trough body/wick low" does not select an exact price | Body meeting boundary versus extreme wick. |
| A03 | v4 3.3 vs v3 3.3 | Same-color pair versus physically non-overlapping gap; momentum unspecified | Define GAP predicate and price/zone anchors. |
| A04 | v4 3.6 | "3rd candle ... after ... created" could mean pattern candle #3 or third subsequent candle | Select offset from the second formation candle. |
| A05 | v4 3.5, 10.2, 10.3 | HTF alignment permits unfresh trade in one place; sweep+SMT exception elsewhere; checklist only fresh | Specify allowed repair routes. Unresolved route is rejected. |
| A06 | v4 4.2 vs 10.3 | Fifth touch described as final touch, checklist says <5 | Select whether fifth touch can be traded; default unresolved. |
| A07 | v4 6.4–6.5 | "all" fresh levels, major swings, exhaustion, short-term, near target unspecified | Define finite history coverage and phase transition/exhaustion criteria. No arbitrary pivot lookahead. |
| A08 | v4 7.1–7.2 | EST versus daylight-saving NY; QT has no timezone and "repeats every 90 minutes" versus four-quarter cycle | Specify session and QT timezone/anchor; all reports always Asia/Karachi. |
| A09 | v4 7.3, 8.4, 10.3 | SMT globally mandatory or EX3-only; inverted comparison undefined; five requested markets lack peers | Select scope, inverse comparison convention, synchronized swing window, and peers. |
| A10 | v4 7.4, 8.4 vs v3 8.4, 9.4 | Fibo sets differ; v3 EX4 Fibo entry becomes v4 Asia sweep/M5 MSS; targets conflict with SNR hierarchy | Select source and target priority; no invented Fibonacci scale-in. |
| A11 | v4 8.1–8.5 | "long wick", "strong", "holds", "few pips", "double", "aligned", OB/base boundaries undefined | Explicit thresholds / holding bars / time alignment / double-apex tolerance required for affected models. |
| A12 | v4 9.2 | Consecutive daily losses vs v3 total daily losses; "big win" cooldown undefined | Version selects loss count; define big-win R threshold; use PKT risk day unless approved otherwise. |
| A13 | v4 9.3 | Phase 3 "close to target" and regression thresholds unspecified; v3 percentages contradict division formulas | Explicit phase transitions; start Phase 1 (0.33%) subject to lower configured risk caps; no automatic escalation without policy. |
| A14 | v4 9.4 | Buffers defined only for Forex/Gold; broker pip sizes require validation | Gold 3.0 price units; Forex pip map must be explicit; crypto/oil/equities blocked until buffers approved. |
| A15 | v4 9.5 | TP1 describes SBR/bearish GAP only, not mirrored sells; 30% could mean original vs remainder | Confirm mirrored sell targets and allocation base; preserve 50/30/20 of initial volume only when approved. |
| A16 | v4 6.1 | Live MN/W wick rejection is allowed, but historical finished candles expose future highs/lows | Build partial HTF bars only from information available at evaluation time; never load future final OHLC. |
| A17 | v4 8.3 | Failed QM and missed entry refer to subjective expected structure; trigger/time window absent | Explicit failed-LS crossing, MISS tolerance, double-apex confirmation and expiry required. |
| A18 | v4 2.2, 7.1, 10.3 | CRT sweep, Asia sweep, OCL and SMT global gates versus optional confluences | Resolve applicability, conservatively require documented checklist evidence until clarified. |

## Explicit evaluation specification

1. **Data:** each instrument has isolated UTC-aware bars, canonical timeframe, broker symbol, source timestamp, and observation timestamp. Reject malformed OHLC, duplicates, future data, gaps in required evidence, stale quotes, unknown sessions and unknown symbol specifications. A closed bar is available only at its close time. MN/W partial rejection uses the observed path, never final historical OHLC.
2. **A/V:** adjacent green/red or red/green closed candles; doji is neither. Use approved price anchor. A new level is available after the second close. Store origin ID, creation time, formation bars, role, revision, touch count, use count and repair evidence.
3. **GAP/OCL/CRT:** GAP follows selected source/definition. OCL requires meeting close/open boundaries at broker tick precision, with no invented equality tolerance. CRT compares the current observed range to the immediately prior selected range; inside, wick sweep and body expansion are separate facts.
4. **Freshness:** test only subsequent candles. Distinguish current first touch from previously mitigated state. Body close across the role boundary creates a new SBR/RBS revision; wick touch consumes freshness. CC repairs only at the approved candle index/direction. Repair never erases prior lifecycle history. Unresolved exception cannot authorize entry.
5. **Trendline:** two ordered A or V anchors; price is linear in time. Initial anchors count as touches 1/2. Count new touch episodes, not every polling tick. Third touch is measurable confluence; subsequent validity follows approved fifth-touch policy. Never substitute screen pixel coordinates for data anchors.
6. **QM:** ordered A–V–A for sell with higher second A, then a closed candle below the intervening V; inverse for buy. Wick-only crossing fails. V4 requires broken reference created before the POI touch, breakout strictly after SNR touch, or at/after TL touch. Each confirmation carries its information-availability timestamp.
7. **Storyline:** MN→D, W→H4, D→H1, H4→H1/M30/M15, H1→M30/M15, M30→M5, M15→M1. All applicable rejection, source freshness, breakout and target evidence is required. Classic requires fresh level; advanced requires proof of exhausted fresh-level universe and valid TL. Starting, middle and ending are separately recorded, not guessed from price proximity.
8. **Confluence:** Asia range uses complete approved session; London/NY sweep must enter an HTF POI. QT computes explicit four 90-minute phases from approved anchor. SMT compares synchronized, already-known swing pairs of configured peers. Missing peer or inverse convention fails required SMT. Fibo ratios and anchors are versioned, not optimized silently.
9. **Catalog:** Apex, LS, SBR/RBS, ERS, GAP QMS; C.APEX, GAP continuation, SBR/RBS continuation; QMC, nested QM, failed TL-QM, MISS, double apex, SNRC1; EX1–EX4 for both directions. Model predicates, timeframe chains and allowed storyline phases are enumerated in the rule catalog. Unsupported/ambiguous required predicates are UNKNOWN and explicitly block that model.
10. **Badges:** at least one applicable, completed LTF badge: rejection, engulfing gap break, engulfing TL break, mini QM, or M5 EMA9 engulf-and-hold. A model-specific badge restriction overrides the generic OR. Wick length and hold duration require policy; EMA warm-up and availability are tested.
11. **Stops/targets:** beyond confirmation extreme by mandatory instrument buffer, rounded outward to tick size. Targets are selected from fresh opposing source structures in documented hierarchy; reject missing/misordered targets, invalid geometry, spread/cost violations or lot constraints. Typical RR examples are not guaranteed or silently imposed minimums.
12. **Risk:** use the lesser of approved strategy phase risk and configured account limits. Enforce losses/day, cooldown, drawdown, daily loss, aggregate open plus reserved risk, margin, market session, spreads, slippage, connectivity and permissions under one order reservation transaction. Unknown external exposure prevents new execution. Live requires separate documented validation and explicit authorization.
13. **Management:** persist signal lifecycle, independent published-signal monitoring, order intent before transmission, uncertain-submit suspension, broker reconciliation, partial exits, BE only after confirmed TP1 reduction, and final exit. No widening/removal of SL. No retry of ambiguous submissions. Reports derive from immutable records.
14. **Human guidance:** education, psychology, confidence, notebook practice, emotional self-rating and author comparisons are documented/journal fields, not numerical entry confirmations. No emotional score is fabricated for an automated system.

## Requirement dependency graph

`approved source/policy → symbol metadata + synchronized observable bars → A/V/GAP/OCL/CRT → freshness/TL/QM → HTF rejection/storyline → session/QT/SMT → model + badge → stops/targets → signal eligibility → chart/publication → risk reservation → broker execution → reconciliation → journal → analytics/reporting`

Each source subsection is mapped in `COMPLIANCE_MATRIX.md`; the full source text is retained so narrative and exceptions cannot disappear during implementation. The matrix distinguishes implemented primitives, gated models, documentation-only material and externally unverified capabilities.
