# MSnR · Trading Ledger

Python trading research and monitoring service for the user-approved **Malaysian SNR / Alchemist v4** specification. The repository includes rule evaluation, a durable event journal, paper execution, a Windows MT5 bridge, chart rendering, Discord delivery, historical replay, reports and a responsive dashboard.

**Operational status:** local engineering validation is recorded in [VALIDATION.md](docs/VALIDATION.md). This repository is **not certified for live trading**. Real broker instruments, terminal behavior, historical edge and forward demo behavior require external validation. No profit, win-rate or native TradingView drawing accuracy is claimed. The base CLI configuration defaults to `paper`; the Windows launcher uses a separate authorized `demo` profile. Live execution requires a separate authorization manifest.

**Windows one-file setup:** [Download Install-MSnR.cmd](https://github.com/airateenarogers-a11y/MSnR/raw/refs/heads/main/Install-MSnR.cmd), save it and double-click it. It installs the project and starts an automatic demo-trading control window. [One-file instructions](docs/ONE_FILE_WINDOWS.md).

**Manual installation:** [Download, installation and user guide](docs/RUN_GUIDE.md). It covers Windows with MT5, Linux/cloud, Docker, dashboard controls, Discord, backtesting, demo mode and troubleshooting.

## Run locally

Python 3.12 and a supported Linux/Windows host are required.

```bash
cd /workspace/MSnR
bash scripts/install.sh
bash scripts/start.sh
# Separate process: market worker (waits safely if no bridge is configured)
bash scripts/worker.sh
```

The dashboard binds local port 8000. `/health` verifies the database. There are no sample trades in the application database. Configure an operator token of at least 32 characters to use authenticated controls. `.env.example` documents variable names; shell processes do not automatically source `.env`. Inject secrets using your process manager, Docker Compose `env_file`, or your host's secure environment settings.

Docker/Compose deployment, including the validated offline image-build route, is documented in [operations](docs/OPERATIONS.md#start-and-stop).

```bash
.venv/bin/msnr doctor
.venv/bin/msnr worker --once
.venv/bin/pytest -q
# Real Chrome tests, if Chrome is installed:
MSNR_CHROME_EXECUTABLE=/workspace/tools/chrome/opt/google/chrome/chrome .venv/bin/pytest -q tests/test_browser.py
```

## Strategy provenance

- [Original v4](docs/sources/strategy-v4.md): authoritative Markdown, unchanged.
- [Original v3](docs/sources/strategy-v3.md): reference only, unchanged.
- [User decisions](docs/DECISIONS.md): approved definitions, exceptions, session clock, buffers, SMT, cooldowns and phases. These clarifications take precedence over conflicting source text.
- [Pre-implementation audit](docs/STRATEGY_AUDIT.md) and [compliance matrix](docs/COMPLIANCE_MATRIX.md).
- `docs/requirements.json`: full subsection text, original line ranges and SHA-256 identifiers.
- [Architecture](docs/ARCHITECTURE.md) and [operations](docs/OPERATIONS.md).

## Project structure

```text
config/default.json              Versioned strategy, instruments and risk defaults
src/msnr/
  domain.py config.py clock.py   Strict inputs, configuration and timezone rules
  data.py                       Historical input and candle availability
  strategy/
    primitives.py               Levels, freshness, QM, trendlines, badges, SMT, CRT, Fibo
    catalog.py                  All 18 named setup models and per-model gates
    engine.py                   Multi-timeframe evaluation and rejection evidence
  store.py migrations/          SQLite WAL, migrations, immutable audit and durable intents
  risk.py execution.py          Risk gates, paper fills, broker intents and reconciliation
  integrations/
    mt5.py                      HTTPS bridge client and official Windows terminal adapter
    discord.py                  Embeds, unique outbox, rate limits, ambiguous-delivery quarantine
    tradingview.py              Chrome capability inspection and verified rendering fallback
  bridge.py                     Authenticated Windows terminal API
  charts.py                     Data-coordinate candlesticks and evidence manifests
  analytics.py                  Measured outcomes, grouping, recommendations and bootstrap
  backtest.py research.py        Replay, embargoed splits, walk-forward and cost sensitivity
  reports.py worker.py           PKT reporting, polling, leases and restart checkpoints
  api.py cli.py                 Authenticated dashboard service and command line
  web/static/                   Complete HTML, CSS and JavaScript dashboard
tests/                          Unit, integration, failure recovery and Chrome E2E tests
scripts/                        Repeatable installation and startup
deployment/                     Docker/Compose and TLS proxy example
docs/                           Specification, decisions, traceability and operations
var/                            Local runtime state; ignored by Git
```

## Market data and execution

Linux does not run the official MT5 terminal package. Run the bridge on a **Windows host with an installed, authenticated MT5 hedging demo account**. Use a private network/TLS gateway. Exact instrument names and aliases are validated against terminal discovery. Netting accounts are refused because independent strategy tickets cannot safely share a net position under this implementation.

The default symbols are XAUUSDm, EURUSDm, USDJPYm, BTCUSDm, ETHUSDm, USOILm, TSLA and GOOGL. Additional instruments require configuration and broker specifications. Missing peers block SMT-required models only. Quote/contract metadata and complete required candle evidence must be available before execution.

Risk defaults are deliberate caps, not claims about the strategy's profitability: 0.33% maximum per trade, 2% daily loss, 5% observed account drawdown, 1% concurrent risk, three positions. Strategy phases are computed but cannot exceed the configured maximum. Match these limits, commission, spread limits, account baseline and prop target to the actual account before demo testing. The 10-minute cooldown applies to every closed trade; ≥3R closes also require a manual dashboard reality check.

## Historical validation

Supply truthful broker OHLCV data, with UTC-aware `time` (and optionally `end`) columns. Required price columns are `open,high,low,close`; `volume` is optional. M1 execution data plus every selected strategy timeframe and any mandatory peers are needed. Import from the Backtesting dashboard after broker specifications have been verified, or use a manifest:

```bash
.venv/bin/msnr backtest /path/to/manifest.json --output var/backtests/new-run.db
```

The manifest contains `datasets` entries (`symbol,timeframe,path,source`), `specifications` keyed by exact symbol (`SymbolSpec` fields), and `spread` in price units. Paths resolve relative to the manifest. Use a fresh output database for each run. `msnr.research.validate(...)` runs fixed-policy in/out-of-sample, embargoed walk-forward and execution-cost sensitivity scenarios. Research never modifies trading rules. No historical results are bundled as evidence of an edge.

## Notifications and charts

Set `MSNR_DISCORD_WEBHOOK` securely. Unknown HTTP delivery is quarantined; webhook APIs cannot promise exactly-once delivery after ambiguous transport failures. A local signal publication and a confirmed Discord delivery have separate audit events.

Use `scripts/install_chrome.py` for a checksum-verified official Chrome install, then `msnr tradingview-check --chrome /path/to/chrome`. The requested chart is fixed in the adapter. A verified broker-data chart is generated for each published signal. Native TradingView screenshots are reference-only until exact feed identity and price/time drawing anchors can be verified. No private TradingView APIs or pixel guesses authorize a signal chart.

## Production gate

Follow [the readiness checklist](docs/READINESS.md) and [operations guide](docs/OPERATIONS.md). All live mode authorization flags default to absent. Build/test success is engineering evidence; it does not establish strategy profitability or broker execution correctness. Do not authorize live execution while any required validation item remains outstanding.
