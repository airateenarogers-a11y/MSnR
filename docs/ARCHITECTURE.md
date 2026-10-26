# MSnR architecture

## Deployment and trust boundaries

Python 3.12 service: FastAPI dashboard/API, one durable worker lease, SQLite WAL with transactional intents/outbox and append-only event journal. SQLite is appropriate for a single account/worker deployment; use backups and local durable storage, never a network filesystem. Multiple accounts use separate databases. Horizontal workers require a future PostgreSQL migration and are not represented as supported.

Windows: official MetaTrader5 Python terminal bridge, authenticated API, loopback by default, TLS required across machines. Bridge performs independent account/mode/symbol/order validation, serializes terminal calls, and persists command identities. Linux uses HTTPS bridge data; Linux does not pretend to execute the Windows MT5 package. Account login remains in the Windows terminal/environment. Never transmit broker passwords to the dashboard.

Chrome/Playwright: persistent user-owned TradingView session, fixed allowed target URL, bounded navigation; no private undocumented chart APIs. Native drawing output is never delivered unless price/time anchoring and source identity can be verified. Deterministic Python candlesticks with data-coordinate overlays are the default verified fallback and label their broker data source. TradingView screenshots are separate reference artifacts when equivalence is unknown.

Discord: persistent unique event outbox, bounded exponential retry only for definitive failures/rate limits, no automatic resend after ambiguous HTTP delivery. Webhooks do not offer exactly-once delivery; ambiguous requests are quarantined for operator reconciliation. All signal status events and reports have stable IDs.

## Modules

| Module | Responsibility |
|---|---|
| `domain`, `config`, `clock` | Strict immutable input models, versioned policy, UTC/PKT boundaries |
| `strategy/primitives`, `strategy/engine`, `strategy/catalog` | Observable structures, per-rule evidence, gated model evaluation |
| `data` | CSV import, MT5 OHLC, canonical timeframes, new-bar deduplication |
| `store`, `migrations` | Transactional state, append-only audit, unique fingerprints, outbox, command reservations |
| `risk`, `execution` | Position sizing, atomic exposure reservation, paper/broker mode separation |
| `integrations/mt5`, `bridge` | Windows terminal RPC and local terminal access |
| `charts`, `integrations/tradingview`, `integrations/discord` | Accurate chart delivery and bounded external I/O |
| `analytics`, `backtest`, `reports` | Net P/L, measured R, drawdown, research splits, PKT reporting |
| `worker`, `api`, `web` | Scheduling, health, authenticated controls and responsive terminal |

## Durable schema and recovery

Schema migrations are versioned. Tables: `events` (immutable, hash chain), `signals` (unique structural fingerprint), `orders` (unique signal intent), `positions`, `fills` (immutable broker deal identities), `outbox` (unique delivery key), `reports` (unique period), `bars` (source-aware identities), `state` (configuration/checkpoints/lease), `research` (versioned recommendations and validation runs). Outcomes cannot be updated/deleted; corrections are new events/fills. Mutable projections can be reconstructed from events. SQLite constraints, immediate transactions and broker reconciliation are correctness boundaries.

On restart reconcile submitted/unknown intents and broker positions before new execution. An unknown request outcome suspends execution. Do not infer order absence from a single missing positions response; inspect deal/order history. Position snapshots alone do not establish realized P/L. Journal/report results come from fills. A lost database or stale account snapshot stops new orders.

## API and dashboard

Read endpoints show status, signals, trades, journal, analytics, source compliance, research and replay results. Mutation endpoints require operator authentication, validate payloads, record audit events, and have no endpoint that bypasses strategy authorization or enables live mode. Kill switch suspends new execution immediately; closing broker exposure is a separate explicit operation, not an unannounced side effect.

Use local-only development binding; production requires TLS reverse proxy and a strong operator token, secure cookies, strict same-origin checks, CSP and no secrets in responses/logs. Settings show credential presence only. Credentials never enter source/config snapshots.

## Research methodology

Replay receives chronological raw data; evaluation sees only bars available at each event. Intrabar stop/target ambiguity is pessimistic (stop first), gap exits use adverse open, entry occurs no earlier than the next executable quote/bar. Commissions, bid/ask spread and directional slippage are explicit. Record rejected setups as well as trades. Unknown policy is a blocked replay, not a zero-trade "successful strategy". Synthetic fixtures validate engineering only. Historical edge needs broker data, sufficient independent trades, untouched out-of-sample periods and forward demo evidence.

## UI concept

A dark, ruled trading ledger whose signature is an evidence rail: **Storyline → Level → Sweep → Badge → Risk → Execution**. Teal is verified evidence, amber is waiting/unknown, red is failed or stopped. Serif headlines and monospaced prices create a journal/terminal distinction; no decorative pseudo-market data. Every missing metric reads "No verified data". Responsive navigation, keyboard focus, labeled controls, table alternatives, reduced motion and 44px targets are part of implementation.
