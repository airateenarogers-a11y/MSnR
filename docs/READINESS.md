# Production readiness verification checklist

Completed items require actual test evidence, not source-file presence. Current results are in `VALIDATION.md`.

- [x] Both supplied Markdown versions read completely before implementation; v4 selected by user.
- [x] Original source files retained; explicit user clarifications versioned.
- [x] Default paper mode; separate live authorization gate; no live orders placed.
- [x] Durable signal fingerprints, command reservations and append-only audit.
- [x] Automated local primitive, lifecycle, risk, failure and Chrome dashboard checks.
- [x] Linux container built and exercised with non-root permissions, authentication, health and repeated one-shot worker startup.
- [ ] Independent strategy review and representative positive/negative historical examples for every model, both directions and every supported instrument.
- [ ] Full advanced-storyline history coverage confirmed; set `advanced_history_complete` only after validating the level universe.
- [ ] Windows official MT5 package/terminal installed and authenticated to a hedging demo account.
- [ ] Broker symbol, session, tick value, lot, filling mode and stop/freeze constraints verified for all markets and peers.
- [ ] Account baseline, daily-loss definition, prior drawdown and prop target reconciled against broker/account contract.
- [ ] Controlled demo partial-fill, modification, SL/TP, restarts, disconnection and uncertain-send drills.
- [ ] Reliable historical data ingested; chronological in/out-of-sample, walk-forward, sensitivity and sample adequacy reviewed.
- [ ] Positive/negative results and forward demo comparisons recorded without cherry-picking.
- [ ] TradingView page access restored; account session, symbol/feed mapping and any native chart interactions verified.
- [ ] Discord real webhook delivery, attachments, rate-limit behavior and scheduled reports verified in an authorized channel.
- [ ] Production TLS, secret storage, backups, restore drill, supervision and monitoring tested on deployment hosts.
- [ ] Screen-reader review on the final deployment, plus accessibility audit with assistive technology.
- [ ] Docker/Windows deployment exercised on the intended infrastructure.
- [ ] Owner's explicit, account-specific live authorization after all required checks above.

Local tests establish specific engineering properties. They do not establish financial edge, full strategy compliance across unseen data, or production readiness.
