# How to download, run and use MSnR

Start in **paper mode**. The dashboard and database run without a broker connection, but real market monitoring needs an authenticated Windows MT5 terminal. Paper mode simulates execution using the available market feed; it does not generate example prices. Demo mode sends actual orders to a demo account. Live mode remains disabled until the separate validation and authorization process is completed.

The local checks and limitations are recorded in [VALIDATION.md](VALIDATION.md). Windows/MT5 and real Discord delivery still need testing on your own accounts.

## 1. Download the project

Open [the GitHub repository](https://github.com/airateenarogers-a11y/MSnR), select the **main** branch, then **Code → Download ZIP**. Extract the ZIP to a folder you control. If the repository is private, sign in to the GitHub account with access.

Alternatively, with Git installed:

```bash
git clone https://github.com/airateenarogers-a11y/MSnR.git
cd MSnR
```

Run every command below from the extracted/cloned project folder. Do not run a second worker against an existing active database.

## 2. Choose your installation

| Installation | Use it when | What runs where |
|---|---|---|
| **Windows, all on one PC** | You want the simplest route to your installed MT5 terminal | MT5, bridge, dashboard and worker on the same Windows PC |
| **Linux/cloud** | You want the dashboard and worker on a server | Linux dashboard/worker plus a separate Windows MT5 bridge |
| **Docker Compose** | You prefer supervised containers | Dashboard/worker in Linux containers plus a separate Windows MT5 bridge |

Install Python **3.12**, 64-bit. Node.js is only needed for the optional automated accessibility audit; it is not needed to run the dashboard. Google Chrome is needed for TradingView capability inspection, but the deterministic signal-chart renderer works without Chrome.

## 3. Windows: install and start locally

Install Python 3.12 from python.org and MT5 from your broker. Open MT5 and log in to a **hedging demo account**. Keep it running. Confirm that the account permits algorithmic/Python trading before demo execution; begin with paper mode regardless.

Open PowerShell in the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mt5]"
.\.venv\Scripts\msnr.exe migrate
```

The committed dependency lock was validated on Linux. The Windows MT5 package and dependencies must be checked on your Windows host; the installation above does not claim a verified Windows deployment.

In the **same PowerShell window**, set local paths and generate two separate temporary credentials:

```powershell
$env:MSNR_CONFIG = "config/default.json"
$env:MSNR_DB = "var/paper.db"
$env:MSNR_BRIDGE_URL = "http://127.0.0.1:8765"
$env:MSNR_OPERATOR_TOKEN = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$env:MSNR_BRIDGE_TOKEN = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$project = (Get-Location).Path
$python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
```

Start the three processes from that window so they inherit the same environment:

```powershell
$bridge = Start-Process -FilePath $python -ArgumentList @("-m", "msnr.cli", "bridge") -WorkingDirectory $project -PassThru
$dashboard = Start-Process -FilePath $python -ArgumentList @("-m", "msnr.cli", "serve") -WorkingDirectory $project -PassThru
$worker = Start-Process -FilePath $python -ArgumentList @("-m", "msnr.cli", "worker") -WorkingDirectory $project -PassThru
```

Each process opens its own console. Look for startup errors there. Check the dashboard's health from the original PowerShell window:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
.\.venv\Scripts\msnr.exe doctor
```

Type `http://127.0.0.1:8000` into the browser address bar **on that PC**. Choose **Sign in**. Copy the operator token to your local clipboard, paste it into the sign-in form, then clear the clipboard:

```powershell
Set-Clipboard -Value $env:MSNR_OPERATOR_TOKEN
# Paste into the dashboard and sign in before running the next command.
Set-Clipboard -Value ""
```

The operator token signs into the dashboard; the bridge token authenticates the worker to MT5. Do not interchange them. These variables last only for this PowerShell session and its child processes. On restart, repeat the environment/startup steps; the journal remains in `var/paper.db`. For unattended service operation, store credentials in your secure process manager and supervise the three processes. Never paste credentials into GitHub, chat, logs or screenshots.

To stop, press **Ctrl+C** in the worker console first, then in the dashboard and bridge consoles. Allow shutdown to finish. If a worker is force-killed, its lease may block replacement workers for up to ten minutes. Do not bypass a lease while an old worker might still be running.

## 4. Linux/cloud: install and start

Ensure `python3 --version` reports 3.12 and its `venv` support is installed. Then:

```bash
bash scripts/install.sh
export MSNR_CONFIG=config/default.json
export MSNR_DB=var/paper.db
```

Generate and save a random token of at least 32 characters in your password manager. Paste it at the following hidden prompt so it does not enter shell history:

```bash
read -r -s -p "Paste operator token (32+ characters): " MSNR_OPERATOR_TOKEN
export MSNR_OPERATOR_TOKEN
```

Start the dashboard and worker from the same shell:

```bash
bash scripts/start.sh >var/dashboard.log 2>&1 &
msnr_dashboard_pid=$!
bash scripts/worker.sh >var/worker.log 2>&1 &
msnr_worker_pid=$!
curl --fail http://127.0.0.1:8000/health
.venv/bin/msnr doctor
```

Type `http://127.0.0.1:8000` into the browser on the same machine and sign in with your operator token. On a remote server, use your authenticated SSH tunnel or approved TLS reverse proxy. Loopback addresses on your laptop do not directly reach a remote server. Keep the service bound to loopback until remote access is configured.

The worker initially reports `waiting_for_market_data`. To receive live quotes, deploy the Windows bridge using [OPERATIONS.md](OPERATIONS.md#windows-demo-bridge), securely set `MSNR_BRIDGE_URL` and the matching `MSNR_BRIDGE_TOKEN` on the Linux host, then restart the worker. A remote bridge URL must use **HTTPS**; plain HTTP is allowed only for same-host loopback development. Leave mode `paper` while verifying the feed.

Stop processes you started from that shell:

```bash
kill -TERM "$msnr_worker_pid" "$msnr_dashboard_pid"
```

For a persistent cloud deployment, use a process supervisor or Docker Compose; background processes can stop when the host/session stops. The cloud onboarding configuration is a saved draft: review/save it in environment settings and publish it to preserve the prepared environment. Files and instructions can persist; running processes must restart.

## 5. Docker Compose

Install Docker Engine/Desktop with Compose. From the project root, copy `.env.example` to `.env` and edit the copy locally. Set `MSNR_OPERATOR_TOKEN` to a random token of at least 32 characters. Leave broker/webhook entries empty until configured. On Unix, restrict access with `chmod 600 .env`.

```bash
docker compose -f deployment/compose.yml up --build -d
docker compose -f deployment/compose.yml ps
docker compose -f deployment/compose.yml logs --tail=100 dashboard worker
```

The dashboard is exposed on host loopback port 8000. Both services share the named `msnr-data` volume. The container runs as a non-root user. Compose reads `.env`; the native shell scripts do **not** automatically load that file.

For a bridge outside the containers, use its approved HTTPS address and configure the network accordingly. `127.0.0.1` **inside a container** refers to that container, not the Windows host or another service.

If the container build cannot reach the package registry but the Linux host can, use the validated offline build route:

```bash
bash scripts/install.sh
.venv/bin/python scripts/build_offline_image.py
.venv/bin/python scripts/verify_container.py
docker compose -f deployment/compose.yml up --no-build -d
```

Stop with `docker compose -f deployment/compose.yml stop`; restart with `docker compose -f deployment/compose.yml start`. Do not use `down -v` unless you intentionally want to delete the persistent trading journal. Back up first.

## 6. What to check on first startup

1. **Overview:** mode is PAPER; connection status matches the actual worker/MT5 state. An empty ledger or absent account value is expected before real data arrives.
2. **Settings → Connections:** configured means a value exists; it does not prove the service accepted it. Inspect the worker and bridge results as well.
3. **Market watch:** confirm all requested broker symbols exist. The defaults are XAUUSDm, EURUSDm, USDJPYm, BTCUSDm, ETHUSDm, USOILm, TSLA and GOOGL. Some brokers do not offer all of them.
4. **Instrument specifications:** verify exact symbol names, tick/pip values, lot steps, tick value in account currency, stop/freeze distances, spreads, sessions and SMT peers. Edit your deployment configuration when names differ; do not silently treat a different instrument as the requested one.
5. **Risk:** fractions use decimal units: `0.0033` means **0.33%**, `0.02` means **2%**. Confirm account baseline, daily-loss interpretation, commission and challenge target. Defaults are starting limits, not broker-specific recommendations.
6. **Signals:** a connected feed does not guarantee a signal. Missing history, a failed mandatory condition or an unavailable required SMT peer must block the affected setup.

## 7. Use the dashboard

| Section/control | What you do |
|---|---|
| Overview | Check mode, connection, account values, active signals, positions and guardrails. |
| Live signals | Inspect the setup, mandatory evidence, entry/stop/targets, status and chart. Ratings measure documented confluence, not a win probability. |
| Trades | Review paper/demo execution records and export CSV. |
| Trading journal | Search permanent events, inspect errors and add notes without rewriting outcomes. |
| Analytics | Review measured results and sample size; an empty history establishes no trading edge. |
| Backtesting | Import broker CSV files for each required timeframe and run historical replay. |
| Reports | Inspect recorded daily/weekly summaries and periods. |
| Settings | Adjust allowed risk limits and instrument selection, inspect connection presence and mechanical policy. Credentials are configured on the host. |
| Suspend execution | Stop **new entries**. Existing protective stops and position management remain active; this button does not liquidate positions. |
| Confirm manual reality check | Acknowledge the review after a ≥3R close. The mandatory ten-minute cooldown still applies. |
| Clear reviewed error suspension | Use only after reconciling the actual cause and unknown order outcomes. It does not replace broker reconciliation. |

Dashboard risk/instrument edits are persisted and audited. Changing execution mode requires a deployment/configuration restart, not an accidental dashboard toggle.

## 8. Connect Discord and inspect TradingView

Create a Discord webhook in the intended server channel using Discord's **channel settings → Integrations → Webhooks**. Store its URL as `MSNR_DISCORD_WEBHOOK` in your deployment's secret/environment settings. Restart the worker after changing its environment. For the single-PC PowerShell route, set it in the original parent shell before starting/restarting the worker; do not put the URL in committed files.

Once configured, the worker can send real signal/status messages and scheduled reports. Daily reports cover `[02:00 PKT yesterday, 02:00 PKT today)`; weekly reports cover Saturday-to-Saturday at 02:00 PKT. No test signal is invented to prove delivery. Verify the actual webhook and attachment behavior in your own channel; unknown transport outcomes are quarantined to avoid blind duplicate sends.

For TradingView capability inspection on Windows with Chrome in its standard location:

```powershell
.\.venv\Scripts\msnr.exe tradingview-check --chrome "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

On the prepared Linux cloud environment:

```bash
.venv/bin/python scripts/install_chrome.py --directory /workspace/tools/chrome
.venv/bin/msnr tradingview-check --chrome /workspace/tools/chrome/opt/google/chrome/chrome
```

Inspection targets the requested TradingView chart. Native price/time drawing anchors have not been verified. Signal images use the deterministic broker-data renderer until that verification succeeds. If the browser reports a certificate error or HTTP 403, follow [the operations guide](OPERATIONS.md#tradingview-and-chrome); do not disable certificate verification.

## 9. Import history and backtest

Export truthful broker bars, one CSV per symbol/timeframe. Required columns are `time,open,high,low,close`; `volume` and explicit `end` are optional. Timestamps must include UTC or a numeric timezone offset, for example the **format** `2026-01-05T10:00:00+00:00`. Data must be ordered and contain valid OHLC geometry. Preserve broker session/bar boundaries; do not relabel local timestamps as UTC without converting them.

In **Backtesting**, select the exact broker symbol and timeframe, supply a truthful source label, and import the CSV. Include M1 execution data, all strategy timeframes needed by the selected models, and any mandatory comparison instruments. Verify broker contract specifications through the connected worker before choosing **Run imported history**. Review the resulting research record even if it contains no trades or negative results.

For offline CLI research, prepare a JSON manifest with:

- `datasets`: entries containing `symbol`, `timeframe`, `path` and `source`; paths are relative to the manifest.
- `specifications`: exact symbol keys mapped to the verified `SymbolSpec` fields in `src/msnr/domain.py`.
- `spread`: exact symbol keys mapped to a documented spread assumption in **price units**.

Run with a fresh output path:

```bash
.venv/bin/msnr backtest /path/to/manifest.json --output var/backtests/research-001.db
```

On Windows, replace `.venv/bin/msnr` with `.\.venv\Scripts\msnr.exe`. A JSON result is written beside the research database. Keep each run separate. The `msnr.research.validate(...)` Python interface supports fixed-policy in/out-of-sample, walk-forward and cost sensitivity analysis. No historical profitability has been established by the bundled synthetic engineering tests.

## 10. Move from paper to demo

Only after the symbols, account, strategy examples and paper behavior are reviewed:

1. Stop the existing worker gracefully. Keep the paper journal.
2. Copy `config/default.json` to an ignored deployment path such as `var/demo-config.json`. Change only `"mode": "paper"` to `"mode": "demo"` and apply your reviewed broker/risk settings.
3. Point both dashboard and worker to `MSNR_CONFIG=var/demo-config.json` and **a separate** `MSNR_DB=var/demo.db`.
4. Confirm the Windows terminal is logged into the intended hedging **demo** account. Keep `MSNR_BRIDGE_ALLOW_LIVE` unset.
5. Restart the services and confirm DEMO in the dashboard. Demo mode can send broker orders when all strategy/execution conditions pass.
6. Exercise acceptance/rejection, partial exits, SL/TP changes, disconnects, uncertain outcomes and restart recovery. Compare broker deal records with the journal.

Do not reuse one active deployment/database across multiple accounts. Live mode has additional account/policy-specific gates. Complete [READINESS.md](READINESS.md) and obtain explicit live authorization separately; this guide does not grant it.

## 11. Back up, update and troubleshoot

Back up the native application database using the CLI's SQLite backup operation:

```bash
.venv/bin/msnr backup /your/secure/backup/location/msnr-backup.db
```

The command uses the database selected by `MSNR_DB`; set the correct one first. Back up the Windows bridge's `var/bridge.db` too, along with reviewed configuration and securely managed credentials. Test restores into an isolated environment before relying on them.

Before updating, suspend new execution, reconcile/manage existing positions, stop the worker gracefully and take backups. With a Git checkout, run `git pull --ff-only`, reinstall dependencies and run the checks. A downloaded ZIP is not a Git checkout: extract a new download into a separate folder and preserve/restore your runtime state deliberately. Never overwrite or delete journals to resolve an update error.

| Problem | Check |
|---|---|
| Dashboard cannot open | Check the dashboard console/log, health endpoint, port 8000 and whether the browser is on the correct host. |
| Sign-in fails | Use the operator token from the dashboard process's current environment, not the bridge token. Restart after changing the environment. |
| Worker waits for market data | Check bridge URL/token, Windows terminal login and reachability; quotes are never fabricated. |
| MT5 fails to initialize | Verify 64-bit Windows/Python, correct terminal instance and demo login; optionally set the documented MT5 terminal path. |
| A symbol is unavailable | Check the broker's exact Market Watch name and configured peer names. Not every broker offers every market. |
| Another worker owns the lease | Stop the original safely; wait for stale-lease expiry after a crash. Do not delete state while its outcome is uncertain. |
| Signals are absent | Review rejection evidence, required history, session, freshness and risk/cooldown gates. Do not weaken mandatory rules to create activity. |
| Discord is silent | Verify webhook presence, network access and outbox results; check channel IDs before retrying uncertain sends. |
| Critical suspension remains | Reconcile broker state and inspect the recorded error before using the reviewed-clear control. |

For engineering checks on Linux, run `.venv/bin/ruff check src tests scripts` and `.venv/bin/pytest -q`. Real browser checks require Chrome and `MSNR_CHROME_EXECUTABLE`; the accessibility audit additionally uses `npm ci` to install the locked `axe-core` development dependency. See [VALIDATION.md](VALIDATION.md) for exact scope and remaining external checks.
