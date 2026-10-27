# Validation record

Recorded 27 October 2026 PKT (26 October UTC). **Local engineering checks pass; production and financial validation remain incomplete.** No live or demo broker order was placed. The application database contains no signals, positions or fills from real markets.

The preserved evidence from the original local validation is in [validation/local-2026-10-27](validation/local-2026-10-27). Files under `artifacts/` are regenerated during local checks; the committed snapshot preserves the results referenced below.

## Evidence obtained

| Check | Observed result | Evidence / reproduction |
|---|---|---|
| Python unit, integration, failure recovery and real Chrome E2E suite | **62 passed, 0 failed, 0 skipped**, 1 dependency deprecation warning | `artifacts/test-results.xml`; command below |
| Python statement coverage | **73% overall**; strategy engine 82%, primitives 85% | `artifacts/coverage.txt`; untested paths remain |
| Static checks and dependency consistency | Ruff passes; `pip check` reports no broken requirements | `ruff check src tests scripts`; `.venv/bin/python -m pip check` |
| Browser controls and layout | Real Google Chrome login, all navigation sections, kill switch, keyboard focus, no browser JS errors, 390px mobile reflow pass | `tests/test_browser.py`; desktop/mobile PNGs in `artifacts/` |
| Automated accessibility | Overview: **0 violations, 22 passing checks, 1 incomplete check** | `artifacts/accessibility.json`; incomplete and screen-reader checks require human review |
| Source integrity and traceability | 92 numbered subsections across both versions and 361 v4 prose/list/table clauses mapped; original source hashes verified | `scripts/traceability.py`, `docs/COMPLIANCE_MATRIX.md`, JSON matrices |
| Deterministic strategy fixture | Raw-candle LS/nested-QM case creates a valid signal; missing candles, absent rejection and newer source touch reject it | `tests/test_engine_pipeline.py`; synthetic fixture, not live performance evidence |
| Execution and recovery | Risk gates, missing evidence, live authorization, duplicate reservations, concurrent exposure, partial exits/BE, uncertain outcomes, restart leases and reconciliation tested | Execution, recovery, bridge and worker tests; broker/HTTP test doubles |
| Persistence and reporting | Hash-chain integrity, immutable history, unique fingerprints, outbox/report deduplication, PKT boundaries and DST behavior tested | Store, integration and recovery tests |
| Linux deployment | Offline image builds from hash-verified dependencies; non-root UID 10001; health 200; authenticated status 200; unauthenticated status 401; two one-shot worker runs release leases and wait for a broker | `artifacts/container-validation.json`; `scripts/verify_container.py` |
| Local application | Database health succeeds, journal chain valid, paper mode, no configured broker/webhook/operator credential | `msnr doctor`; no secret values recorded |

Reproduce the suite after installation:

```bash
MSNR_CHROME_EXECUTABLE=/workspace/tools/chrome/opt/google/chrome/chrome \
  .venv/bin/pytest -q --cov=msnr --cov-report=term-missing \
  --junitxml=artifacts/test-results.xml
.venv/bin/ruff check src tests scripts
.venv/bin/python -m pip check
.venv/bin/python scripts/traceability.py
.venv/bin/python scripts/build_offline_image.py
.venv/bin/python scripts/verify_container.py
```

The Chrome executable used was Google Chrome 156.0.8078.47. Its downloaded package SHA-256 was `6c92cd22e90c6e3e255d782991543fa2091db8614e8536a971a7433a5c4d7ac8`, verified against Google's HTTPS package index. This checksum describes the tested package; the installer checks the current published package rather than assuming that version forever.

## Windows worker recovery update — 27 October 2026 UTC

The worker-lock repair is included in installer source `92a52a70e9f886b5e9551d120f5f35cafd834f15`, packaged by commit `bdea3fb5bda87b6a08ae36d2f4992bda59d0803f`.

- Local complete suite with real Chrome: **96 passed, 3 Windows-only skips**, one dependency deprecation warning. Ruff and dependency consistency checks pass.
- [Native Windows verification](https://github.com/airateenarogers-a11y/MSnR/actions/runs/40428272700/job/121939396916): dependency installation, desktop/worker tests, DPAPI encryption, Windows PowerShell checks, first installation, state-preserving upgrade and repeat launch all passed.
- Regression coverage includes active/unknown owner rejection, verified dead-owner recovery, legacy lease expiry, Python redirector/interpreter PID differences, orphaned worker cleanup, reconnecting a stopped worker, and graceful lease release. The installer upgrade test preserves the encrypted vault byte-for-byte, retains a runtime sentinel, verifies the backup, and starts/stops real local services on each invocation.
- The public installer download was byte-compared with the generated file. SHA-256: `c1e1e2c06b3c09273de1c7ac589f141154f847fc1158b3b2995907e486535feb`.

These checks run without connecting an MT5 account or sending an order. They validate the Windows service/installer repair; the broker and strategy-validation limits below still apply. See [the exact recovery procedure](ONE_FILE_WINDOWS.md#if-the-worker-stopped-with-workerlease_unavailable).

## MT5 feed timeout update — 27 October 2026 UTC

Installer source `eb4f8ffb2675918473d820f6feb27d22176b770b` is packaged by `41f58b115bcf628d444ab19607538323a5b67ba7`.

- Local complete suite with real Chrome: **109 passed, 3 Windows-only skips**, one dependency deprecation warning. Ruff and dependency consistency checks pass.
- [Windows verification](https://github.com/airateenarogers-a11y/MSnR/actions/runs/40432905446/job/121954650708) passed dependency installation, desktop/worker/feed regressions, DPAPI, PowerShell validation, first install, state-preserving upgrade and repeat launch. [Linux verification](https://github.com/airateenarogers-a11y/MSnR/actions/runs/40432905446/job/121954651060) also passed.
- Controlled tests cover a blocked native-history call with concurrent HTTP requests, immediate busy responses, responsive diagnostics, native error-code propagation, route-specific read deadlines, no order retries, persistent feed backoff, consolidated notifications, incremental history refresh/gap recovery, account-change cache invalidation, broker alias consistency, old unresolved orders in reconciliation, and a read-only diagnostic report without credentials/account numbers.
- The public pinned installer was compared byte-for-byte with the generated file. SHA-256: `8748f799d9047b26fe3f153f62d5d990e0a070f7279c52150abaaf04f1c6e4d6`.

The Windows runner validates processes, packaging and dependency imports. **MT5 market responses in automated tests are controlled doubles, not a live terminal account.** The user's laptop must run **Check MT5 (read only)** to verify the native connection, prices and M1 candles; full multi-timeframe history and broker execution require their own checks. No real-account connection or order placement was performed during this repair. See [timeout troubleshooting](ONE_FILE_WINDOWS.md#if-mt5-is-logged-in-but-the-app-reports-timeouts).

## Limits of this evidence

- The 18 named strategy models have catalogue gates and code paths. There is **not yet a complete independent positive/negative historical fixture corpus for every model, direction and market**. A traceability mapping identifies code/test responsibility; it is not proof of every clause's correctness on unseen data. Advanced storylines remain blocked by default until complete level-history coverage is verified.
- No reliable broker history was supplied. No measured trading edge, win rate, profitability or out-of-sample advantage is claimed. Synthetic fixtures and a no-trade replay establish specific engineering behavior only. Replay models configured spread, commission and slippage; it does not reproduce all broker financing/swaps, order-book liquidity or intrabar tick paths. Adverse-first bar handling is a conservative assumption, not a tick reconstruction.
- The official Windows MT5 terminal, the eight exact instrument contracts, actual fills/partial fills, market-session restrictions and production TLS were not available for validation. MT5 integration tests use a terminal double. Netting accounts are explicitly refused. Account risk baselines start from observed deployment/day equity and require reconciliation with any earlier account history.
- Discord tests exercise delivery/error behavior through controlled HTTP transports. No real webhook was configured or message sent. Scheduled reports require real-channel delivery verification.
- TradingView native annotations are **unverified**. Earlier access was denied by the environment proxy; the final curl check reached an HTTP 403 response, and Chrome reported `ERR_CERT_AUTHORITY_INVALID`. Certificate checking was not disabled. The capability result is preserved in `artifacts/tradingview/capability.json`. A supported browser trust configuration and authorized page access are needed before inspecting login, feed identity and drawing anchors. Broker-data rendering remains the signal-chart fallback.
- The regular Docker build encountered DNS/proxy resolution failures in its build namespace. The supported offline route downloaded hash-verified wheels through the host and installed them with container build networking disabled. That Linux route passed the runtime check; the final deployment host, reverse proxy, backup/restore process and Windows host still require validation.
- Accessibility automation covered the overview and browser navigation/reflow. It does not replace a complete screen-reader review or all populated/error-state accessibility checks.

## Complete the external validation

1. Review and save the cloud environment configuration draft, then publish the environment. This saves installation/startup instructions and the installed filesystem; a saved draft alone does not activate it. Fresh-task restoration has not been independently verified. The GitHub source and run guide are published separately from the cloud environment snapshot; publishing code does not activate cloud settings.
2. Follow [OPERATIONS.md](OPERATIONS.md) to deploy an authenticated Windows MT5 **hedging demo** bridge. Enter the bridge URL/token, operator token and Discord webhook securely in deployment settings. Allow the selected bridge's exact hostname.
3. Verify broker symbols, peers, tick/pip values, lot constraints, stop/freeze distances, sessions, costs and account risk baselines. Gather complete historical datasets for every required timeframe. Review the v4/decision matrix against independently labelled examples for every model before enabling affected setups.
4. Run chronological out-of-sample and walk-forward research, review sample adequacy and negative outcomes, and compare against sustained forward demo results. Exercise broker disconnects, uncertain sends, partial fills and restart recovery on the demo account.
5. Verify actual Discord reports, browser trust/page access, production TLS, backups/restores and monitoring. Complete [READINESS.md](READINESS.md). Only the account owner can provide the separate explicit live authorization after those checks.

The delivery contains executable modules, source and local test evidence. It is not represented as a fully validated production trading service.
