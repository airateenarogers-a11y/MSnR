# User-approved strategy decisions

These explicit user clarifications override ambiguous wording in the uploads. They are not claims that the uploaded PDF has been independently verified.

1. V4 is authoritative; v3 is reference only.
2. A/V price line is adjacent candle close/open body junction. The highest/lowest formation wick is the separate apex used for stop placement and refinement.
3. CC is pattern candle 3: immediately after the two formation candles; bullish for support, bearish for resistance.
4. Sessions and 90-minute QT cycles use `America/New_York`, including DST. Daily/weekly reporting uses `Asia/Karachi`.
5. SMT is optional for standard MSNR storylines. It is mandatory for QT×SMT, Circle Fibonacci SMT, H1 POI liquidity-sweep hybrids, and explicitly SMT-labelled EX3. Missing comparison data blocks those models only.
6. Peers: XAU→XAG, EUR→GBP, USDJPY→USDCHF (relationship not yet unambiguously selected), BTC↔ETH, USOIL→UKOIL or XLE, TSLA→QQQ/NQ or NVDA, GOOGL→MSFT or QQQ/NQ. Prefer the first configured available exact broker symbol; do not silently substitute instruments. Broker aliases must be explicitly validated.
7. Buffers beyond wick: Forex 30 pips; Gold 3.0 price units; BTC 300–500; ETH 15–30; oil 0.30–0.50; TSLA/GOOGL 0.50–1.50 or 0.3–0.5%. Current fixed-price configuration chooses the upper endpoints. Gold tick count is computed from broker tick size, never assumed to be 300 for every broker.

Further proposed parameter definitions remain unapproved until a user reply is recorded. Unresolved definitions must remain visible in compliance and block affected predicates. Prop phase 3 and subjective exhaustion/major-win thresholds are not silently enabled.

8. User confirmed GAP at same-direction body junction, TL entry touches 3/4 only, mirrored sell support targets, and original-volume 50/30/20 partial exits.
9. User approved rejection wick >=2 body lengths and >=1 tick, body engulfing, one additional closed M5 EMA9 hold candle, <=1 tick level alignment, <=3 instrument pips MISS, <=2 ticks double apex. These are approved implementation definitions, not claims extracted verbatim from v4.

10. Final user clarification: Part 3 at <=20% remaining source-to-target distance OR after two consecutive continuation breakouts. All closed trades impose a 10-minute cooldown. >=3R closes additionally require an authenticated manual reality check. Phase 3 at target minus two percentage points or three consecutive Phase-2 wins; -5% from peak demotes to Phase 1. USDJPY/USDCHF uses direct comparison. Challenge target defaults to the given 10% example, is explicit configuration, and must match the actual prop contract. Configured risk caps always apply.


## V5 superseding decisions — 27 October 2026 PKT

V5 is now primary. Earlier approved v4 details fill gaps only where consistent with v5. The uploaded Python files are references, never strategy authority. The reuploaded v5 has the same SHA-256 as the audited source.

- Evaluation profile: 0.33% baseline; 0.50% at +2% equity or three consecutive Phase-1 wins; 1.00% at +5% or within two percentage points of the evaluation target. Phase-2 peak drawdown of 3% halves the allowed risk. Phase-3 peak drawdown of 5% resets Phase 1. Independent daily/drawdown ceilings can suspend execution first.
- Funded profile: 0.50% hard maximum; Phase 2 at +2%; Phase 1 during drawdown recovery. Operational recovery interpretation: equity must recover its high-water mark before promotion. `evaluation_mode` defaults false, independently of demo/real broker mode. The operator's existing per-trade ceiling is retained and can be lower than the ladder.
- EX1: H1 POI liquidity-sweep retest with M1/M5 micro QM/MSS. EX2: broken H1 SBR/RBS retest with M5 EMA9 hold. EX3: Asian/London range sweep into H1 POI with M1/M5 reversal. EX4: H1 OCL/GAP retest with M5 badge. Earlier mandatory SMT for H1 liquidity-sweep models applies to EX1/EX3; it is optional for EX2/EX4.
- ERS explicitly bypasses the main closed QM breakout only while the structure is developing. The latest ERS level must itself be usable and receive a closed LTF badge, with verified macro storyline alignment. An unusable latest ERS does not permit fallback to an older ERS.
- V5 badge definitions supersede the earlier universal engulfing restriction. M5/M15 directional body breaks and EMA9 cross/hold do not require an extra engulfing candle.
- V5 mappings are MN1→D1, W1→H4, D1→H1, H4→M15, H1→M5. The validation candle is on the mapped frame. Native chart timestamps are UTC epoch seconds without a guessed broker/server-hour offset.
- V5 Asia is 20:00–00:00 New York; QT quarters divide each 90-minute cycle into 22.5-minute intervals. Exact QT Q1/Q2 boundaries need sub-minute data; M1 candles spanning a half-minute boundary cannot establish the precise range. This model rejects rather than approximate that boundary.
