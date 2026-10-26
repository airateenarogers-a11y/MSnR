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
