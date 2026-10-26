# Operations and troubleshooting

## Windows demo bridge

1. Install Python 3.12, MT5 and Google Chrome on a Windows host. Log in to the intended **hedging demo** account in MT5; confirm AutoTrading and Python trading permission.
2. Install this checkout: `py -3.12 -m venv .venv`, then `.venv\Scripts\python -m pip install -e ".[mt5]"`. Pin the resulting Windows-specific MT5 version in that deployment after verification; the Linux lock cannot validate a Windows-only terminal wheel.
3. Inject `MSNR_BRIDGE_TOKEN` (at least 32 random characters) using a secret manager. Optionally provide `MT5_TERMINAL_PATH`, `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` through the host environment; never put them in repository files or screenshots.
4. Run `.venv\Scripts\msnr bridge --host 127.0.0.1 --port 8765`. Expose only through an authenticated HTTPS reverse proxy on the approved private network. Client TLS certificate verification stays enabled.
5. On the cloud host, set `MSNR_BRIDGE_URL=https://your-private-bridge`, the matching `MSNR_BRIDGE_TOKEN`, and a separate `MSNR_OPERATOR_TOKEN`. Add the actual bridge hostname to environment egress settings. Its hostname is unknown until the user selects a host; no guessed destination is allowed.
6. Begin in paper mode with real bridge quotes. Verify all eight exact broker symbols, tick values in account currency, pip sizes, lot steps, minimum/maximum lot, stop/freeze distances, execution/filling modes, market sessions and peers. Set exact aliases explicitly if the broker differs. An alias discovery is reported for config review; the engine never rewrites symbol identity silently.
7. Use a distinct database/config for demo execution. Test broker acceptance/rejection, partial fills, SL/TP modification, target partials, history/deal recovery and restarts. Do not reuse the paper journal as a live account ledger.

The bridge currently requires hedging accounts. For a netting account, implementing and validating a per-symbol allocation ledger is a separate engineering requirement; the bridge refuses execution rather than merging independent strategy positions.

## Start and stop

For a host with Docker, securely create the runtime `.env` described by `.env.example`, including an operator token of at least 32 characters. On a normal network, use `docker compose -f deployment/compose.yml up --build -d`. The two services share a durable named data volume; the image runs as UID 10001. Configure the TLS proxy separately before remote use.

If the Docker build namespace cannot resolve the host's proxy/package registry, use the verified offline installation route from a Linux Python 3.12 host matching the container architecture:

```bash
.venv/bin/python scripts/build_offline_image.py
.venv/bin/python scripts/verify_container.py
docker compose -f deployment/compose.yml up --no-build -d
```

This downloads dependencies with the committed hashes on the host, builds a local application wheel, then installs into the image with build networking disabled. It still needs access to the base image and host package downloads. It does not disable TLS or checksum checks. `verify_container.py` uses a disposable database and transient credential, cleans up its own container, and writes a credential-free result to `artifacts/container-validation.json`. It never supplies broker or webhook credentials.

Run `scripts/start.sh` and `scripts/worker.sh` as separate supervised processes. Installation persists files; server/worker processes must restart after a restored cloud snapshot. Use the existing isolated checkout; do not create a Git worktree unless explicitly requested.

SIGTERM/SIGINT stops the worker gracefully and releases its lease. Abrupt death may retain a lease for up to ten minutes. A second worker must not bypass it while the original may still be trading. Use one worker per database/account. Database locks serialize reservation and outbox claims. Keep SQLite on local durable storage.

The kill switch stops **new execution**, not existing protective stops or position management. It does not silently liquidate an account. Critical failures set a separate persistent suspension. Reconcile and review uncertain intents before clearing that suspension through an authenticated operational action; never edit order statuses to "retry" an unknown submission.

## Risk and manual reality check

Ten-minute cooldowns follow every closed trade. A ≥3R result also blocks new evaluations until the operator presses **Confirm manual reality check** in Settings. That action is authenticated and audited; it does not shorten the cooldown. No automatic process clicks it.

Prop phase 2 begins at +3% from the configured baseline. Phase 3 begins at target minus 2 percentage points or after three Phase-2 wins. A 5% fall from peak demotes to Phase 1. The maximum-risk cap still applies; default cap 0.33% intentionally prevents automatic increase above that amount until configured. Prop target defaults to the user's 10% example; change it to the actual contract. Broker risk baselines begin at the first observed deployment equity and the first observation of each PKT day; they do not reconstruct unobserved intraday/overnight equity peaks. An account with existing risk history requires independently verified baseline reconciliation before authorization.

## Journal durability and backups

`msnr backup /safe/path/msnr-backup.db` uses SQLite's online backup API, including WAL state. Keep encrypted, access-controlled off-host backups and perform restore drills. `msnr doctor` verifies the event hash chain. SQL triggers prevent updates/deletes of audit events, fills, reports and research records. This is an application audit mechanism, not protection against a privileged database administrator. Record corrections as new events.

Use separate databases for paper, backtest, demo and live accounts. Never change starting paper capital after execution exists. Dashboard CSV export escapes spreadsheet formula prefixes.

## Reporting

Daily intervals are `[previous day 02:00 PKT, current day 02:00 PKT)`; weekly intervals are `[previous Saturday 02:00, current Saturday 02:00)`. A Saturday daily and weekly report are distinct. On recovery, the most recently completed period is created once; the application does not invent missing history. Reports preserve period totals, snapshot timestamp, open positions, execution issues and sample sufficiency. Unknown/unavailable unrealized valuation stays null.

## Discord

Set the webhook in secure runtime settings and allow `discord.com` egress. Never paste it in chat or commit it. Default mentions are disabled. A 429 respects `retry_after`; connect failures have bounded retries. A timeout after possible delivery, server ambiguity or process death during send becomes `unknown`. Check the channel for the stable event ID before any operator-authorized recovery. Delivery idempotency is local; Discord offers no idempotency key for this failure window.

## TradingView and Chrome

Install Chrome with `python scripts/install_chrome.py --directory /workspace/tools/chrome`. Export `MSNR_CHROME_EXECUTABLE=/workspace/tools/chrome/opt/google/chrome/chrome`. The installer verifies the download against Google's HTTPS package index SHA-256. It never disables TLS/checksum verification.

Allow TradingView's chart and asset/data domains in egress settings. Earlier access returned **proxy CONNECT 403**. The final curl check reached an HTTP 403 response; Chrome reported `ERR_CERT_AUTHORITY_INVALID`. These do not establish a valid application session. Apply saved network changes and configure the host's approved browser trust chain; do not disable certificate verification. Then rerun `msnr tradingview-check`. Supply any TradingView login through a browser session on your own host; no password is requested in chat. UI, feed mapping and native drawing anchoring remain unverified until tested. The deterministic chart fallback remains the authoritative delivered image.

## Failure playbook

| Symptom | Response |
|---|---|
| Worker waiting for market data | Configure and verify the Windows bridge; no dummy quotes are inserted. |
| Missing symbol or peer | Inspect broker discovery, configure exact aliases/peer mapping, retry read-only access. |
| Missing candle evidence | Fetch the required timeframes and full confirmation interval; do not replace gaps with synthetic candles. |
| Database unavailable | Keep execution stopped. Restore storage and verify the audit chain before reconciliation. |
| Unknown order outcome | Query broker deals/order history and durable command status. Never submit a new ID for the same signal. |
| Partial broker fill | Reconcile actual volume. If exact 50/30/20 lots violate broker constraints, suspend new orders and review; no volume is invented. |
| TP1 filled but BE modification rejected | Keep existing broker SL; suspend new execution and inspect freeze/stops distances. Never remove the SL. |
| Market closed / stale quote | Wait for fresh broker ticks and valid permissions; stale ticks cannot authorize orders. |
| TradingView proxy 403 | Apply only the required network-domain additions; keep verified broker chart fallback. |
| Discord unknown delivery | Match stable event ID against actual channel messages before deciding whether to resend. |

## Explicit live authorization

Do not create an authorization file until all required checks in `READINESS.md` have passed and the owner explicitly approves live trading for a named account/policy. The file schema is `account_id`, `policy_hash`, `explicit_authorization: true`, `demo_validated: true`, `historical_validated: true`, `approved_by`, UTC-aware `authorized_at` and `expires_at`. Point `live_authorization_file` at an access-controlled path and set mode `live`. Separately, the Windows host requires `MSNR_BRIDGE_ALLOW_LIVE=EXPLICITLY_AUTHORIZED`. The software never creates these approvals automatically. A manifest assertion is an operator record, not an independent attestation of profitability.
