from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..clock import PKT, iso, utcnow
from ..domain import Signal
from ..store import Store


def signal_embed(signal: Signal, status="Awaiting Entry") -> dict:
    return {
        "username": "MSnR · Trading Ledger",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"{signal.symbol} | {signal.direction} SETUP",
                "color": 0x66D5BA if signal.direction == "BUY" else 0xF39185,
                "description": f"**{signal.rating} — "
                + {
                    "A+": "Exceptional Confluence",
                    "A": "Strong Setup",
                    "B": "Valid Setup",
                    "C": "Lower-Quality Setup",
                }[signal.rating]
                + "**",
                "fields": [
                    {"name": "Entry", "value": f"{signal.entry:,.5f}", "inline": True},
                    {"name": "Stop loss", "value": f"{signal.stop:,.5f}", "inline": True},
                    {
                        "name": "Targets / planned R",
                        "value": "\n".join(
                            f"TP{i + 1}: {t:,.5f} · {r:.2f}R"
                            for i, (t, r) in enumerate(zip(signal.targets, signal.rr))
                        ),
                        "inline": True,
                    },
                    {"name": "Why this trade?", "value": signal.reason[:1024]},
                    {"name": "What invalidates this setup?", "value": signal.invalidation[:1024]},
                    {"name": "Status", "value": status, "inline": True},
                    {
                        "name": "Time",
                        "value": signal.created_at.astimezone(PKT).strftime("%d %b %Y · %H:%M PKT"),
                        "inline": True,
                    },
                    {
                        "name": "Context",
                        "value": f"{signal.htf} → {signal.timeframe} · {signal.setup}",
                        "inline": True,
                    },
                ],
                "footer": {
                    "text": f"ID {signal.id} · Rating measures confluence, not probability or guaranteed profit."
                },
                "image": {"url": "attachment://chart.png"},
            }
        ],
    }


class Discord:
    def __init__(self, store: Store, webhook: str, client=None):
        parsed = urlsplit(webhook)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ("discord.com", "discordapp.com")
            or not parsed.path.startswith("/api/webhooks/")
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError("Use an HTTPS Discord webhook URL without query parameters")
        self.store = store
        self.webhook = webhook
        self.client = client or httpx.Client(timeout=20, follow_redirects=False)

    def recover(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE outbox SET status='unknown',error='Process stopped during delivery; manual reconciliation required' WHERE status='sending'"
            )

    def deliver_one(self, now=None) -> dict | None:
        now = now or utcnow()
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM outbox WHERE status='pending' AND available_at<=? ORDER BY available_at LIMIT 1",
                (iso(now),),
            ).fetchone()
            if not row:
                return None
            row = dict(row)
            db.execute("UPDATE outbox SET status='sending',attempts=attempts+1 WHERE id=?", (row["id"],))
        p = json.loads(row["payload"])
        body = p.get("body")
        if body is None:
            body = {
                "allowed_mentions": {"parse": []},
                "embeds": [
                    {
                        "title": f"MSnR | {p.get('type', 'Update').title()}",
                        "description": p.get("summary")
                        or "\n".join(
                            f"**{k.replace('_', ' ').title()}:** {v}" for k, v in p.items() if k != "chart"
                        )[:4000],
                        "footer": {"text": "Event " + row["event_key"]},
                    }
                ],
            }
        status = "failed"
        error = None
        remote = None
        delay = 0
        try:
            if p.get("chart"):
                with Path(p["chart"]).open("rb") as f:
                    response = self.client.post(
                        self.webhook + "?wait=true",
                        data={"payload_json": json.dumps(body)},
                        files={"files[0]": ("chart.png", f, "image/png")},
                    )
            else:
                response = self.client.post(self.webhook + "?wait=true", json=body)
            if response.status_code in (200, 204):
                status = "sent"
                remote = str(response.json().get("id", "")) if response.content else None
            elif response.status_code == 429:
                status = "pending"
                try:
                    delay = min(3600, max(1, float(response.json().get("retry_after", 1))))
                except (ValueError, TypeError):
                    delay = 60
                error = "Discord rate limit"
            elif response.status_code >= 500:
                status = "unknown"
                error = "Server error; delivery outcome ambiguous"
            else:
                error = f"Discord HTTP {response.status_code}"
        except (httpx.ConnectError, httpx.ConnectTimeout):
            status = "pending"
            delay = min(300, 2 ** (row["attempts"] + 1))
            error = "Connection not established"
        except (httpx.ReadError, httpx.ReadTimeout, httpx.WriteError, httpx.WriteTimeout):
            status = "unknown"
            error = "Transport interrupted; delivery may have occurred"
        except (OSError, ValueError):
            status = "failed"
            error = "Invalid local attachment or response"
        if row["attempts"] >= 4 and status == "pending":
            status = "failed"
        with self.store.transaction() as db:
            db.execute(
                "UPDATE outbox SET status=?,available_at=?,remote_id=?,error=? WHERE id=?",
                (status, iso(now + timedelta(seconds=delay)), remote, error, row["id"]),
            )
            self.store.event(
                "notification." + status, row["id"], {"event_key": row["event_key"], "error": error}, now, db
            )
        return {"status": status, "id": row["id"]}
