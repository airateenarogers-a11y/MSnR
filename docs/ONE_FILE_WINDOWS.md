# One-file Windows installer and launcher

Download [Install-MSnR.cmd](https://github.com/airateenarogers-a11y/MSnR/raw/refs/heads/main/Install-MSnR.cmd), save it as **Install-MSnR.cmd**, and double-click it on **64-bit Windows 10/11 or a Windows VPS with a desktop/RDP session**. If your browser displays the text, use **Save link as**; ensure the name does not end in `.txt`.

You do not need Git, Docker, Node.js or a separate project ZIP. Internet access is required for the first installation. Run it as your normal Windows user. Vendor installers may display their own permission/setup prompts.

## First run

The file:

1. Reuses Python 3.12 x64 if installed; otherwise downloads the official Python.org Windows installer and verifies its publisher signature.
2. Downloads the pinned MSnR source archive and checks its SHA-256 before extraction.
3. Creates a private installation at `%LOCALAPPDATA%\MSnR\app` and installs the Windows Python/MT5 dependencies using `requirements-windows.lock` hashes.
4. Finds Google Chrome and MT5. If missing, it launches their official, publisher-verified installers. Complete MT5's installation prompts. If either optional installer fails or is cancelled, the local paper dashboard can still run; the launcher explains what remains unavailable.
5. Generates separate dashboard/bridge credentials and encrypts them using Windows DPAPI for your Windows user.
6. Starts the dashboard and paper worker, opens the dashboard, and creates the **MSnR Trading Ledger** desktop shortcut.

The control window offers **Copy sign-in key**. Click it, paste the key into the dashboard's **Sign in** form, and keep the control window open while monitoring. The key is not printed in setup logs or placed in a URL. Closing the control window clears the clipboard if it still contains that key.

## Connect your broker

The installer cannot create a broker account or supply its credentials.

1. Open your broker's MT5 terminal and sign in to a **hedging demo account**.
2. In the MSnR control window, use **Choose MT5 terminal** if the detected installation is not the correct one. Select its `terminal64.exe`.
3. Click **Connect MT5**. If MT5 is still starting, finish signing in and click again.
4. Confirm the dashboard receives the expected symbols and specifications.

The worker receives the bridge connection only after a hedging demo account is verified. The application remains in **PAPER mode**: market data comes from MT5 and execution is simulated locally. This launcher does not activate broker demo orders or live trading, and refuses an edited desktop configuration that requests either. Follow the separate [run guide](RUN_GUIDE.md#10-move-from-paper-to-demo) for a reviewed demo-execution deployment.

Click **Configure Discord** to enter an optional webhook locally. It is saved in the encrypted credential vault and the worker restarts with the setting. Leave the field empty to disable Discord. Do not send passwords, tokens or webhook URLs in chat.

## Later starts and shutdown

Use the desktop shortcut or double-click the same downloaded file again. It reuses the installed release, credentials and journal. A second invocation refuses to start another copy while the first control window is open. A different source release will not overwrite an existing installation automatically.

Keep the PC/VPS and the MSnR control window running. Keep MT5 running for market data. The software operates independently of this chat, but it is **not** installed as a Windows background service or scheduled task.

Close the MSnR control window to stop its worker, bridge and dashboard. Shutdown may take several seconds. It stops only processes this launcher created. A Windows job object terminates its child services if the launcher is forcibly closed; a forced termination can leave a lease that expires after ten minutes. Reopen after that expiry if a crash left a lease. Never erase the journal or blindly reset an unknown order/lease to force a restart.

## Files and recovery

| Location under `%LOCALAPPDATA%\MSnR` | Purpose |
|---|---|
| `Start-MSnR.cmd` | Installed copy used by the desktop shortcut |
| `downloads\` | Verified source and dependency download cache |
| `app\.msnr-source.json` | Installed source release identity |
| `app\.venv\` | Isolated Python packages |
| `app\var\desktop\paper.db` | Persistent paper journal |
| `app\var\desktop\paper-config.json` | Dedicated paper-only configuration |
| `app\var\desktop\credentials.dpapi` | Encrypted credentials tied to your Windows profile |
| `app\var\desktop\dashboard.log`, `worker.log`, `bridge.log` | Service troubleshooting logs |
| `app\var\bridge.db` | Durable bridge command state |

Use **Open logs** to inspect errors. Back up the databases with the documented SQLite backup procedure and protect your Windows profile/credentials. A DPAPI file copied to another Windows account may not decrypt; do not replace a corrupt/unreadable vault silently. Restore it or perform a deliberate credential reset while preserving the journal.

The launcher uses a free loopback port near 8000 for the dashboard and near 8765 for the bridge. Use **Open dashboard** to reach the chosen port. It does not open a public firewall port, change system execution policy, enable live trading, or start at Windows login.

For a failed package installation, rerun the same launcher. If packages were damaged after a successful installation, stop the control window, remove **only** `app\.desktop-dependencies-ready`, and rerun to reinstall dependencies. Never remove `app\var` as a repair step.

For an upgrade, back up runtime state and use the [operations guide](OPERATIONS.md). The installer intentionally pins the reviewed source identified in [windows-release.json](../deployment/windows-release.json); it does not execute an unverified moving branch. Python 3.12.10 is the Python.org Windows installer baseline when Python is absent. The Windows host and its Python/vendor applications still need normal security-update maintenance.

## Validation scope

Local tests cover service startup/authentication, duplicate prevention, paper-only enforcement, inherited live-flag removal, credential-file preservation, shutdown and worker lease release. PowerShell checks cover parsing, archive checksums, HTTPS requirements and preservation of existing folders.

The GitHub **windows-desktop** job tests DPAPI, the native process lifecycle, Windows PowerShell parsing and the packaged installer twice. Its installer test reuses the runner's Python and skips interactive Chrome/MT5 installers. Actual broker login, vendor installation prompts, Windows desktop visual behavior and real MT5/Discord operation still require validation on your PC. See the [workflow](https://github.com/airateenarogers-a11y/MSnR/actions/workflows/test.yml) and [production checklist](READINESS.md).
