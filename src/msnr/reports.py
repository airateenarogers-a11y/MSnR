from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from hashlib import sha256

from .analytics import summarize, trades, recommendations
from .clock import PKT, iso, period
from .store import Store, encode


def schedule_reports(store: Store, now: datetime, starting_equity: float) -> list[str]:
    emitted = []
    for kind in ("daily", "weekly"):
        start, end = period(now, kind)
        key = f"{kind}:{iso(start)}:{iso(end)}"
        if store.rows("SELECT id FROM reports WHERE id=?", (key,)):
            continue
        records = [
            r
            for r in trades(store)
            if r["closed_at"] and start <= datetime.fromisoformat(r["closed_at"]) < end
        ]
        metrics = summarize(records, starting_equity)
        executed = store.rows(
            "SELECT COUNT(DISTINCT f.order_id) AS n FROM fills f WHERE f.at>=? AND f.at<? AND json_extract(f.payload,'$.kind')='entry'",
            (iso(start), iso(end)),
        )[0]["n"]
        signal_rows = store.rows(
            "SELECT status,COUNT(*) AS n FROM signals WHERE created_at>=? AND created_at<? GROUP BY status",
            (iso(start), iso(end)),
        )
        fills = store.rows("SELECT payload FROM fills WHERE at>=? AND at<?", (iso(start), iso(end)))
        metrics["period_net_realized"] = sum(json.loads(f["payload"])["net"] for f in fills)
        errors = store.rows(
            "SELECT kind,COUNT(*) AS n FROM events WHERE at>=? AND at<? AND kind IN ('execution.rejected','order.rejected','order.unknown','worker.error') GROUP BY kind",
            (iso(start), iso(end)),
        )
        open_rows = store.rows("SELECT id,symbol,payload FROM positions WHERE status='open'")
        payload = {
            "kind": kind,
            "start": iso(start),
            "end": iso(end),
            "boundaries": "[start,end), 02:00 Asia/Karachi",
            "metrics": metrics,
            "trades_executed": executed,
            "signal_counts": signal_rows,
            "execution_issues": errors,
            "open_positions": [{"id": r["id"], "symbol": r["symbol"]} for r in open_rows],
            "unrealized": store.state("unrealized", None),
            "unrealized_as_of": store.state("valuation_at", None),
            "lessons": recommendations(records),
            "best": max(records, key=lambda x: x["net"]) if records else None,
            "worst": min(records, key=lambda x: x["net"]) if records else None,
            "by_instrument": {
                s: summarize([r for r in records if r["symbol"] == s], starting_equity)
                for s in {r["symbol"] for r in records}
            },
            "by_rating": {
                rating: summarize([r for r in records if r["rating"] == rating], starting_equity)
                for rating in {r["rating"] for r in records}
            },
            "forward_comparison": "No matched historical/forward validation pair has been registered; no comparison is inferred.",
        }
        win = f"{metrics['win_rate']:.1%}" if metrics["win_rate"] is not None else "No closed trades"
        summary = (
            f"**{kind.title()} trading report**\n{start.astimezone(PKT):%d %b %H:%M} → {end.astimezone(PKT):%d %b %H:%M} PKT\n"
            f"Closed trades: {metrics['closed_trades']} | Wins: {metrics['wins']} | Losses: {metrics['losses']}\n"
            f"Net realized: {metrics['period_net_realized']:,.2f} | Win rate: {win}\n"
            f"Open positions: {len(open_rows)} | Execution issue groups: {len(errors)}\n"
            "All figures derive from persisted fills. Missing broker valuations remain unavailable."
        )
        counts = {r["status"]: r["n"] for r in signal_rows}

        def numeric(value):
            return "Unavailable" if value is None else f"{value:,.2f}"

        fields = [
            {
                "name": "Signals / executed trades",
                "value": f"{sum(counts.values())} / {executed}",
                "inline": True,
            },
            {"name": "Wins / losses", "value": f"{metrics['wins']} / {metrics['losses']}", "inline": True},
            {
                "name": "Win rate / profit factor",
                "value": f"{win} / {numeric(metrics['profit_factor'])}",
                "inline": True,
            },
            {
                "name": "Net realized / unrealized",
                "value": f"{numeric(metrics['period_net_realized'])} / {numeric(payload['unrealized'])}",
                "inline": True,
            },
            {
                "name": "Expectancy / average R",
                "value": f"{numeric(metrics['expectancy'])} / {numeric(metrics['average_r'])}",
                "inline": True,
            },
            {
                "name": "Realized drawdown",
                "value": "Unavailable"
                if metrics["max_drawdown"] is None
                else f"{metrics['max_drawdown']:.2%}",
                "inline": True,
            },
            {
                "name": "Best / worst closed trade",
                "value": "No closed trades"
                if not records
                else f"{payload['best']['symbol']}: {payload['best']['net']:,.2f} / {payload['worst']['symbol']}: {payload['worst']['net']:,.2f}",
            },
            {
                "name": "By instrument",
                "value": "\n".join(
                    f"{s}: {m['closed_net']:,.2f} · {m['closed_trades']} closed"
                    for s, m in payload["by_instrument"].items()
                )[:1024]
                or "No closed trades",
            },
            {
                "name": "Missed / invalidated",
                "value": f"Expired: {counts.get('Expired', 0)} · Invalidated: {counts.get('Invalidated', 0)}",
            },
            {
                "name": "Open positions (current snapshot)",
                "value": ", ".join(r["symbol"] + " " + r["id"][:8] for r in open_rows)[:1024]
                or "None recorded",
            },
            {
                "name": "Execution issues",
                "value": "\n".join(r["kind"] + ": " + str(r["n"]) for r in errors) or "None recorded",
            },
            {
                "name": "Evidence and next steps",
                "value": "\n".join(r["recommendation"] for r in payload["lessons"])[:1024],
            },
        ]
        body = {
            "allowed_mentions": {"parse": []},
            "embeds": [
                {
                    "title": f"MSnR | {kind.title()} trading report",
                    "description": summary,
                    "color": 0x66D5BA,
                    "fields": fields,
                    "footer": {"text": "Period ID " + key + " · No historical outcome is fabricated."},
                }
            ],
        }
        notification = {"type": kind + " report", "body": body}
        if kind == "weekly":
            from .charts import equity_chart

            chart = Path("var/reports") / (sha256(key.encode()).hexdigest() + ".png")
            equity_chart(metrics["equity_curve"], chart)
            notification["chart"] = str(chart)
            body["embeds"][0]["image"] = {"url": "attachment://chart.png"}
        with store.transaction() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO reports VALUES(?,?,?,?,?)",
                (key, kind, iso(start), iso(end), encode(payload)),
            ).rowcount
            if inserted:
                store.enqueue("report:" + key, notification, now, db)
                store.event(
                    "report.created", key, {"kind": kind, "start": iso(start), "end": iso(end)}, now, db
                )
                emitted.append(key)
    return emitted
