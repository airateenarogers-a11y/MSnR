from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math

import numpy as np

from .clock import session
from .store import Store


def trades(store: Store) -> list[dict]:
    rows = store.rows(
        "SELECT o.*,s.symbol,s.payload AS signal_payload FROM orders o JOIN signals s ON s.id=o.signal_id ORDER BY o.created_at"
    )
    result = []
    for row in rows:
        signal = json.loads(row["signal_payload"])
        fills = store.rows("SELECT * FROM fills WHERE order_id=? ORDER BY at,id", (row["id"],))
        values = [json.loads(f["payload"]) for f in fills]
        net = sum(f["net"] for f in values)
        entry = next((f for f in values if f["kind"] == "entry"), None)
        exit_fills = [f for f in values if f["kind"] != "entry"]
        result.append(
            {
                "id": row["id"],
                "signal_id": row["signal_id"],
                "symbol": row["symbol"],
                "direction": signal["direction"],
                "timeframe": signal["timeframe"],
                "rating": signal["rating"],
                "setup": signal["setup"],
                "status": row["status"],
                "mode": json.loads(row["payload"])["mode"],
                "risk_phase": json.loads(row["payload"]).get("risk_phase", 1),
                "opened_at": row["created_at"],
                "closed_at": fills[-1]["at"] if row["status"] == "closed" and fills else None,
                "entry": entry["price"] if entry else None,
                "exit": sum(f["price"] * f["volume"] for f in exit_fills)
                / sum(f["volume"] for f in exit_fills)
                if exit_fills
                else None,
                "volume": row["volume"],
                "net": net,
                "costs": sum(f["cost"] for f in values),
                "risk_cash": row["risk"],
                "realized_r": net / row["risk"] if row["risk"] > 0 and row["status"] == "closed" else None,
                "session": session(datetime.fromisoformat(row["created_at"])),
                "reason": signal["reason"],
                "confirmations": [e["rule"] for e in signal["evidence"]],
                "fills": values,
            }
        )
    return result


def summarize(records: list[dict], starting_equity: float = 100000) -> dict:
    closed = sorted([r for r in records if r["status"] == "closed"], key=lambda r: r["closed_at"])
    outcomes = [r["net"] for r in closed]
    wins = [x for x in outcomes if x > 0]
    losses = [x for x in outcomes if x < 0]
    equity = starting_equity
    peak = equity
    maximum = 0.0
    curve = []
    for row in closed:
        equity += row["net"]
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else None
        maximum = max(maximum, dd or 0)
        curve.append({"at": row["closed_at"], "equity": equity, "drawdown": dd})
    rvalues = [r["realized_r"] for r in closed if r["realized_r"] is not None]
    holds = [
        (datetime.fromisoformat(r["closed_at"]) - datetime.fromisoformat(r["opened_at"])).total_seconds()
        for r in closed
    ]
    n = len(closed)
    # Wilson binomial interval makes limited sample sizes visible without implying stationarity.
    interval = None
    if n:
        p = len(wins) / n
        z = 1.96
        den = 1 + z * z / n
        center = (p + z * z / (2 * n)) / den
        width = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
        interval = [max(0, center - width), min(1, center + width)]
    return {
        "closed_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": n - len(wins) - len(losses),
        "net_realized": sum(r["net"] for r in records),
        "closed_net": sum(outcomes),
        "win_rate": len(wins) / n if n else None,
        "loss_rate": len(losses) / n if n else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "expectancy": sum(outcomes) / n if n else None,
        "average_r": sum(rvalues) / len(rvalues) if rvalues else None,
        "max_drawdown": maximum if n else None,
        "average_holding_seconds": sum(holds) / len(holds) if holds else None,
        "win_rate_95_wilson": interval,
        "sample_sufficient": n >= 30,
        "minimum_sample": 30,
        "equity_curve": curve,
        "drawdown_basis": "Closed-trade realized equity; intratrade account drawdown is a separate risk control",
    }


def analytics(store: Store, starting_equity=100000) -> dict:
    records = trades(store)
    result = summarize(records, starting_equity)
    for dimension in ("symbol", "timeframe", "session", "rating", "setup", "mode"):
        groups = defaultdict(list)
        for record in records:
            groups[record[dimension]].append(record)
        result["by_" + dimension] = {key: summarize(value, starting_equity) for key, value in groups.items()}
    signals = store.rows("SELECT status,COUNT(*) AS count FROM signals GROUP BY status")
    result["signal_lifecycle"] = {r["status"]: r["count"] for r in signals}
    total = sum(r["count"] for r in signals)
    result["signal_to_trade_conversion"] = len([r for r in records if r["fills"]]) / total if total else None
    result["execution_errors"] = store.rows(
        "SELECT kind,COUNT(*) AS count FROM events WHERE kind IN ('order.rejected','order.unknown','execution.rejected') GROUP BY kind"
    )
    return result


def recommendations(records: list[dict]) -> list[dict]:
    closed = [r for r in records if r["status"] == "closed"]
    result = []
    if len(closed) < 30:
        return [
            {
                "status": "insufficient_evidence",
                "sample": len(closed),
                "recommendation": "Collect at least 30 independent closed trades before comparative inference; never enable a rule change automatically.",
            }
        ]
    groups = defaultdict(list)
    for r in closed:
        groups[(r["symbol"], r["setup"])].append(r)
    for (symbol, setup), rows in groups.items():
        if len(rows) >= 10 and sum(r["net"] for r in rows) < 0:
            result.append(
                {
                    "status": "proposal_only",
                    "symbol": symbol,
                    "setup": setup,
                    "sample": len(rows),
                    "mean_net": sum(r["net"] for r in rows) / len(rows),
                    "recommendation": "Review spread, slippage and confirmation evidence for this losing subgroup; evaluate any proposed restriction on untouched out-of-sample data before approval.",
                }
            )
    return result or [
        {
            "status": "no_supported_change",
            "sample": len(closed),
            "recommendation": "No subgroup has sufficient evidence for a change under the declared minimum sample rules.",
        }
    ]


def monte_carlo(r_values: list[float], simulations=1000, seed=42) -> dict:
    if len(r_values) < 30:
        return {"status": "insufficient_sample", "sample": len(r_values), "minimum": 30}
    if not 100 <= simulations <= 10000:
        raise ValueError("simulations must be 100–10000")
    rng = np.random.default_rng(seed)
    samples = rng.choice(np.asarray(r_values, float), size=(simulations, len(r_values)), replace=True)
    cumulative = np.cumsum(samples, axis=1)
    peaks = np.maximum.accumulate(np.concatenate([np.zeros((simulations, 1)), cumulative], axis=1), axis=1)[
        :, 1:
    ]
    dd = np.max(peaks - cumulative, axis=1)
    return {
        "status": "measured_bootstrap",
        "seed": seed,
        "simulations": simulations,
        "sample": len(r_values),
        "terminal_r_5_50_95": np.quantile(cumulative[:, -1], [0.05, 0.5, 0.95]).tolist(),
        "drawdown_r_5_50_95": np.quantile(dd, [0.05, 0.5, 0.95]).tolist(),
        "limitation": "IID bootstrap ignores serial dependence; this is scenario analysis, not a profit forecast.",
    }
