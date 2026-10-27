# One-file Windows installer and launcher

Download [Install-MSnR.cmd](https://github.com/airateenarogers-a11y/MSnR/raw/refs/heads/main/Install-MSnR.cmd), save it as **Install-MSnR.cmd**, and double-click it on **64-bit Windows 10/11 or a Windows VPS with a desktop/RDP session**. If your browser displays the text, use **Save link as**; ensure the name does not end in `.txt`.

You do not need Git, Docker, Node.js or a separate project ZIP. Internet access is required for the first installation. Run it as your normal Windows user. Vendor installers may display their own permission/setup prompts.

## First run

The file:

1. Reuses Python 3.12 x64 if installed; otherwise downloads the official Python.org Windows installer and verifies its publisher signature.
2. Downloads the pinned MSnR source archive and checks its SHA-256 before extraction.
3. Creates a private installation at `%LOCALAPPDATA%\MSnR\app` and installs the Windows Python/MT5 dependencies using `requirements-windows.lock` hashes.
4. Finds Google Chrome and MT5. If missing, it launches their official, publisher-verified installers. Complete MT5's installation prompts. If either optional installer fails or is cancelled, the local dashboard can still run; the launcher explains what remains unavailable.
5. Generates separate dashboard/bridge credentials and encrypts them using Windows DPAPI for your Windows user.
6. Starts the dashboard and demo worker, opens the dashboard, and creates the **MSnR Trading Ledger** desktop shortcut. It prioritizes your already-running MT5 terminal and does not reinstall MT5 when that session is detected.

The control window offers **Copy sign-in key**. Click it, paste the key into the dashboard's **Sign in** form, and keep the control window open while monitoring. The key is not printed in setup logs or placed in a URL. Closing the control window clears the clipboard if it still contains that key.

## Connect your broker

The installer cannot create a broker account or supply its credentials.

1. Open your broker's MT5 terminal and sign in to a **hedging demo account**.
2. In the MSnR control window, use **Choose MT5 terminal** if the detected installation is not the correct one. Select its `terminal64.exe`.
3. Click **Connect MT5**. If MT5 is still starting, finish signing in and click again.
4. Confirm the dashboard receives the expected symbols and specifications.

The worker receives the bridge connection only after a hedging demo account is verified. The launcher starts **automatic DEMO execution**, as authorized by the owner. It can place orders on the connected demo account once all strategy and risk checks pass. MT5 must have Algo Trading enabled and external Python trading permitted. Real/live accounts are refused; the launcher does not change those MT5 permissions by blindly toggling a button. The configured kill switch, loss/exposure limits, cooldowns and manual reality-check rule still apply. No qualifying setup means no trade.

V4 plus the approved clarification record remains authoritative. Missing mandatory evidence rejects the setup. Existing engineering tests do not establish 100% compliance across every model and real-market history; full historical/model validation remains outstanding. The demo account is the authorized forward-testing environment.

Click **Configure Discord** to enter an optional webhook locally. It is saved in the encrypted credential vault and the worker restarts with the setting. Leave the field empty to disable Discord. Do not send passwords, tokens or webhook URLs in chat.

## Later starts and shutdown

Use the desktop shortcut or double-click the same downloaded file again. It reuses the installed release, credentials and journal. A second invocation refuses to start another copy while the first control window is open. For an update, close all MSnR control/setup windows first and leave MT5 running. The new launcher preserves the previous installation under `backups/`, carries forward the complete `app/var` runtime directory and any `.env`, then installs the verified new release. It refuses to update while MSnR Python services are running. A dependency-install failure before service startup restores the previous installation; once new services start, history is never rolled back automatically.

Keep the PC/VPS and the MSnR control window running. Keep MT5 running for market data. The software operates independently of this chat, but it is **not** installed as a Windows background service or scheduled task.

Close the MSnR control window to stop its worker, bridge and dashboard. Shutdown may take several seconds. It stops only processes this launcher created. A Windows job object terminates its child services if the launcher is forcibly closed. New worker locks record the host, PID and process creation identity: a replacement may recover a lock only when that local process is positively known to have ended. Live, inaccessible or unverifiable owners keep their locks. Old releases created locks without process metadata; those legacy locks must expire (up to ten minutes after the last renewal). The control window shows a stopped worker and the lock expiry instead of claiming execution is enabled. Use Connect MT5 to retry after recovery. Never delete the journal or blindly reset an unknown order/lease.

### If the worker stopped with `worker.lease_unavailable`

This means the database still has a worker owner. It does not indicate an MT5 login failure. Leave MT5 running, close all MSnR control/setup windows, download the current installer from the link above, and run that new file once. The installer backs up the old installation and preserves the journal, settings and encrypted credentials. If the control window reports a legacy lock expiry, wait until that time and click **Connect MT5**. A lock that keeps extending belongs to another active worker; stop that MSnR instance normally first.

The repaired launcher verifies each worker using a unique launch identifier because Windows Python can run its interpreter under a different PID from its launcher. Each service has its own Windows process job so restarting a worker also cleans up its child processes. The control window must show **Worker: running** and the dashboard must show current market data before treating the feed as connected.

### If MT5 is logged in but the app reports timeouts

Keep the existing MT5 terminal open. Close MSnR, download the latest installer above, and run that new file. This updates the application and preserves its runtime data. An open chart proves the terminal can display market data; the separate Python connection still needs a successful read.

1. Click **Check MT5 (read only)** in the updated control window. It independently attaches to the selected terminal, reads account mode/permissions, discovers broker symbols, and requests a quote plus five M1 candles per enabled instrument. It never sends, changes or closes an order.
2. Click **Copy MT5 report** to see/share the result. The JSON contains symbol names, actual prices, quote ages, candle counts, operation timings and MT5 error codes. It excludes the account number, balance, passwords, tokens and webhook. A native call that exceeds the 90-second diagnostic budget is reported with the operation that was in progress.
3. Click **Connect MT5**. In the dashboard's **Overview → Market watch**, verify the bid/ask prices, quote timestamps and per-instrument status. A readable old quote during market closure is labelled with its age; it is not a tradable live quote. A successful five-candle probe does not establish that every strategy timeframe has sufficient history.
4. If a previous version latched **Critical-error suspension**, first confirm current quotes and a complete reconciliation. Then use **Settings → Clear reviewed error suspension** once. Existing unknown/partial orders, journal-integrity failures, kill switches and risk restrictions are not bypassed. Temporary read delays in this update use a separate automatic feed wait instead of creating that permanent latch.

The update gives cold history/deal reads a bounded 90-second HTTP deadline, avoids proxy routing for loopback traffic, and rejects queued requests while the native terminal is busy. Bridge logs identify the operation, symbol, timeframe, elapsed time and native error code. The authenticated `/diagnostics` endpoint exposes the active operation without waiting for the native lock.

Subsequent history reads update the latest three bars, refresh the full requested window every five minutes, and reload after gaps; failed reads never fall back to cached prices. Higher-timeframe evaluation begins only after a new closed M1 candle is observed. Reconciliation includes the preceding day and every older unresolved/open local order, instead of scanning from 2020 on every poll. The complete broker position list still detects untracked exposure. Strategy checks, all required timeframes and risk rules remain in force.

Only explicit broker aliases are resolved: the desktop configuration now includes `TSLA → TSLAm` and `GOOGL → GOOGLm`, and preserves any operator aliases. The actual resolved symbol is used consistently in market data, strategy evaluation, journal records and orders. Optional missing SMT peer data does not prevent standalone MSNR evaluation; models that require SMT still reject missing peer evidence.

One persistent feed incident replaces separate notifications for every affected market. Retries back off to at most once per minute, and feed notices are limited to one per 15 minutes. Pending legacy per-market failure notices are marked cancelled with an audit event; their records and all trading outcomes remain intact. No real broker connection or profitable execution is claimed from the automated test results alone.

## Files and recovery

| Location under `%LOCALAPPDATA%\MSnR` | Purpose |
|---|---|
| `Start-MSnR.cmd` | Installed copy used by the desktop shortcut |
| `downloads\` | Verified source and dependency download cache |
| `app\.msnr-source.json` | Installed source release identity |
| `app\.venv\` | Isolated Python packages |
| `app\var\desktop\demo.db` | Persistent demo journal |
| `app\var\desktop\demo-config.json` | Dedicated demo configuration; live mode refused |
| `app\var\desktop\credentials.dpapi` | Encrypted credentials tied to your Windows profile |
| `app\var\desktop\dashboard.log`, `worker.log`, `bridge.log` | Service troubleshooting logs |
| `app\var\bridge.db` | Durable bridge command state |

Use **Open logs** to inspect errors. Back up the databases with the documented SQLite backup procedure and protect your Windows profile/credentials. A DPAPI file copied to another Windows account may not decrypt; do not replace a corrupt/unreadable vault silently. Restore it or perform a deliberate credential reset while preserving the journal.

The launcher uses a free loopback port near 8000 for the dashboard and near 8765 for the bridge. Use **Open dashboard** to reach the chosen port. It does not open a public firewall port, change system execution policy, enable live trading, or start at Windows login.

For a failed package installation, rerun the same launcher. If packages were damaged after a successful installation, stop the control window, remove **only** `app\.desktop-dependencies-ready`, and rerun to reinstall dependencies. Never remove `app\var` as a repair step.

For an upgrade, back up runtime state and use the [operations guide](OPERATIONS.md). The installer intentionally pins the reviewed source identified in [windows-release.json](../deployment/windows-release.json); it does not execute an unverified moving branch. Python 3.12.10 is the Python.org Windows installer baseline when Python is absent. The Windows host and its Python/vendor applications still need normal security-update maintenance.

## Validation scope

Local tests cover service startup/authentication, duplicate prevention, demo/paper isolation and live-mode rejection, inherited live-flag removal, credential-file preservation, shutdown and worker lease release. PowerShell checks cover parsing, archive checksums, HTTPS requirements and preservation of existing folders.

The GitHub **windows-desktop** job tests DPAPI, the native process lifecycle, Windows PowerShell parsing and first installation, a state-preserving upgrade and a repeat launch. Its installer test reuses the runner's Python and skips interactive Chrome/MT5 installers. Actual broker login, vendor installation prompts, Windows desktop visual behavior and real MT5/Discord operation still require validation on your PC. See the [workflow](https://github.com/airateenarogers-a11y/MSnR/actions/workflows/test.yml) and [production checklist](READINESS.md).
