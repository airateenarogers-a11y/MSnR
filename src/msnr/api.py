from __future__ import annotations

from datetime import datetime
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import time

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .analytics import analytics, trades, recommendations
from .clock import iso, utcnow
from .config import Settings, RiskLimits, load, secret_status
from .domain import Model
from .store import Store, encode
from uuid import uuid4


class Login(Model):
    token: str = Field(min_length=1, max_length=1024)


class Control(Model):
    enabled: bool


class JournalNote(Model):
    entity_id: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=4000)
    emotional_state: int | None = Field(default=None, ge=1, le=10)


class DatasetRequest(Model):
    symbol: str = Field(min_length=1, max_length=40)
    timeframe: str
    source: str = Field(min_length=3, max_length=120)
    csv: str = Field(min_length=20, max_length=5_000_000)


class InstrumentSelection(Model):
    symbols: tuple[str, ...]


def create_app(settings: Settings | None = None, store: Store | None = None):
    settings = settings or load()
    store = store or Store(os.getenv("MSNR_DB", "var/msnr.db"))
    app = FastAPI(title="MSnR Trading Ledger", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.settings = settings
    static = Path(__file__).parent / "web/static"
    attempts = {}
    session_key = secrets.token_bytes(32)

    def authenticated(request: Request):
        token = os.getenv("MSNR_OPERATOR_TOKEN", "")
        authorization = request.headers.get("authorization", "")
        if token and hmac.compare_digest(authorization, "Bearer " + token):
            return True
        cookie = request.cookies.get("msnr_session", "")
        try:
            expiry, signature = cookie.split(".", 1)
            valid = hmac.compare_digest(
                signature, hmac.new(session_key, expiry.encode(), hashlib.sha256).hexdigest()
            )
            if token and valid and int(expiry) > time.time():
                return True
        except (ValueError, TypeError):
            pass
        return False

    def read_access(request: Request):
        if os.getenv("MSNR_OPERATOR_TOKEN"):
            if not authenticated(request):
                raise HTTPException(401, "Operator sign-in required")
        elif request.client and request.client.host not in ("127.0.0.1", "::1", "testclient"):
            raise HTTPException(403, "Configure an operator token before remote access")

    def write_access(request: Request):
        if not authenticated(request):
            raise HTTPException(401, "Operator authentication required for controls")
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin control request rejected")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

    @app.get("/health")
    def health():
        try:
            store.rows("SELECT 1")
            return {"status": "ok", "database": "available", "live_trading": "disabled_without_authorization"}
        except Exception:
            raise HTTPException(503, "Database unavailable; execution must remain stopped")

    @app.post("/api/login")
    def login(body: Login, request: Request, response: Response):
        key = request.client.host if request.client else "unknown"
        recent = [t for t in attempts.get(key, []) if time.time() - t < 60]
        if len(recent) >= 5:
            raise HTTPException(429, "Too many sign-in attempts; retry in one minute")
        token = os.getenv("MSNR_OPERATOR_TOKEN", "")
        if len(token) < 32 or not hmac.compare_digest(body.token, token):
            attempts[key] = recent + [time.time()]
            raise HTTPException(401, "Operator token unavailable or incorrect")
        expiry = str(int(time.time() + 3600))
        digest = hmac.new(session_key, expiry.encode(), hashlib.sha256).hexdigest()
        response.set_cookie(
            "msnr_session",
            expiry + "." + digest,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            max_age=3600,
        )
        return {"authenticated": True}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie("msnr_session")
        return {"authenticated": False}

    @app.get("/api/status", dependencies=[Depends(read_access)])
    def status():
        worker = store.state("worker_health", None)
        instruments = store.state("instrument_status", {})
        mapping = store.state("broker_symbols", {})
        for configured in settings.instruments:
            symbol = mapping.get(configured.symbol, configured.symbol)
            quote = store.state("quote:" + symbol)
            if quote:
                instruments.setdefault(configured.symbol, {}).update(
                    broker_symbol=symbol, bid=quote["bid"], ask=quote["ask"], quote_at=quote["time"]
                )
        fresh = bool(
            worker
            and worker.get("status") in ("running", "loading_market_data")
            and (utcnow() - datetime.fromisoformat(worker["at"])).total_seconds() < 30
        )
        return {
            "mode": settings.mode,
            "policy_hash": settings.policy.digest,
            "policy_version": settings.policy.version,
            "worker": worker,
            "worker_fresh": fresh,
            "kill": store.state("kill", False),
            "suspended": store.state("suspended", False),
            "feed_blocked": store.state("feed_blocked", False),
            "reality_check_required": store.state("reality_required", False),
            "account": store.state("account_snapshot", None),
            "instruments": instruments,
            "configured_instruments": [i.symbol for i in settings.instruments if i.enabled],
            "active_signals": len(
                store.rows(
                    "SELECT id FROM signals WHERE status IN ('Validated','Published','Triggered','Active')"
                )
            ),
            "open_positions": len(store.rows("SELECT id FROM positions WHERE status='open'")),
            "credentials": secret_status(),
            "authenticated_controls": bool(os.getenv("MSNR_OPERATOR_TOKEN")),
            "limitations": [
                "Live broker validation has not been completed.",
                "A signal rating is measured confluence, not a predicted win probability.",
            ],
        }

    @app.get("/api/signals", dependencies=[Depends(read_access)])
    def signals(symbol: str | None = None, status: str | None = None):
        rows = store.rows("SELECT * FROM signals ORDER BY created_at DESC LIMIT 500")
        return [
            {
                **json.loads(r["payload"]),
                "status": r["status"],
                "chart": f"/api/charts/{r['id']}" if r["chart_path"] else None,
            }
            for r in rows
            if (symbol is None or r["symbol"] == symbol) and (status is None or r["status"] == status)
        ]

    @app.get("/api/charts/{signal_id}", dependencies=[Depends(read_access)])
    def chart(signal_id: str):
        rows = store.rows("SELECT chart_path FROM signals WHERE id=?", (signal_id,))
        if not rows or not rows[0]["chart_path"]:
            raise HTTPException(404, "No verified chart")
        p = Path(rows[0]["chart_path"]).resolve()
        if not p.is_relative_to(Path("var/charts").resolve()) or not p.is_file():
            raise HTTPException(404, "Chart unavailable")
        return FileResponse(p, media_type="image/png")

    @app.get("/api/trades", dependencies=[Depends(read_access)])
    def trade_list(symbol: str | None = None):
        return [r for r in trades(store) if symbol is None or r["symbol"] == symbol]

    @app.get("/api/journal", dependencies=[Depends(read_access)])
    def journal(search: str = "", limit: int = 100):
        if not 1 <= limit <= 1000:
            raise HTTPException(422, "Limit must be 1–1000")
        rows = store.rows(
            "SELECT * FROM events WHERE kind LIKE ? OR entity_id LIKE ? OR payload LIKE ? OR at LIKE ? ORDER BY seq DESC LIMIT ?",
            ("%" + search + "%", "%" + search + "%", "%" + search + "%", "%" + search + "%", limit),
        )
        return [{**r, "payload": json.loads(r["payload"])} for r in rows]

    @app.post("/api/journal", dependencies=[Depends(write_access)])
    def add_note(body: JournalNote):
        return {"id": store.event("journal.note", body.entity_id, body.model_dump())}

    @app.get("/api/analytics", dependencies=[Depends(read_access)])
    def stats():
        return analytics(store, settings.risk.paper_balance)

    @app.get("/api/research", dependencies=[Depends(read_access)])
    def research():
        return {
            "recommendations": recommendations(trades(store)),
            "runs": [
                {**r, "payload": json.loads(r["payload"])}
                for r in store.rows("SELECT * FROM research ORDER BY created_at DESC LIMIT 100")
            ],
        }

    @app.get("/api/reports", dependencies=[Depends(read_access)])
    def report_list():
        return [
            {**r, "payload": json.loads(r["payload"])}
            for r in store.rows("SELECT * FROM reports ORDER BY end_at DESC LIMIT 100")
        ]

    @app.get("/api/settings", dependencies=[Depends(read_access)])
    def config():
        current = settings.model_dump()
        current["risk"] = store.state("runtime_risk", current["risk"])
        selected = store.state("runtime_instruments", None)
        if selected is not None:
            for instrument in current["instruments"]:
                instrument["enabled"] = instrument["symbol"] in selected
        return {
            "config": current,
            "credential_presence": secret_status(),
            "pending_risk": store.state("pending_risk", None),
            "mode_change": "Requires validated deployment configuration; live cannot be enabled from this dashboard.",
            "notifications_enabled": store.state("notifications_enabled", True),
        }

    @app.put("/api/settings/instruments", dependencies=[Depends(write_access)])
    def instruments(body: InstrumentSelection):
        if not set(body.symbols) <= {i.symbol for i in settings.instruments} or len(body.symbols) != len(
            set(body.symbols)
        ):
            raise HTTPException(422, "Select unique configured instruments")
        store.set_state("runtime_instruments", list(body.symbols))
        store.event("settings.instruments_updated", "configuration", {"symbols": body.symbols})
        return {
            "message": "Instrument selection saved. Existing positions continue to be managed even when new setups are disabled."
        }

    @app.put("/api/settings/notifications", dependencies=[Depends(write_access)])
    def notifications(body: Control):
        store.set_state("notifications_enabled", body.enabled)
        store.event("settings.notifications_updated", "configuration", {"enabled": body.enabled})
        return {
            "message": "Notification delivery "
            + ("enabled" if body.enabled else "paused")
            + ". Pending events remain in the durable outbox."
        }

    @app.put("/api/settings/risk", dependencies=[Depends(write_access)])
    def risk(body: RiskLimits):
        if body.paper_balance != settings.risk.paper_balance and store.rows("SELECT id FROM orders LIMIT 1"):
            raise HTTPException(
                409,
                "Starting capital cannot be changed after recorded execution. Use a new isolated paper account database.",
            )
        store.set_state("runtime_risk", body.model_dump())
        store.event("settings.risk_updated", "configuration", body.model_dump())
        return {
            "status": "saved",
            "message": "Risk limits saved. The worker applies them before its next evaluation; historical settings remain in the audit journal.",
        }

    @app.post("/api/datasets", dependencies=[Depends(write_access)])
    def dataset(body: DatasetRequest):
        from .data import TIMEFRAMES, read_csv

        if body.timeframe not in TIMEFRAMES:
            raise HTTPException(422, "Unsupported timeframe")
        if body.symbol not in {i.symbol for i in settings.instruments} | {
            p for i in settings.instruments for p in i.peer
        }:
            raise HTTPException(422, "Instrument is not configured")
        path = Path("var/datasets") / (str(uuid4()) + ".csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.csv)
        try:
            data = read_csv(path, body.symbol, body.timeframe, body.source)
        except (ValueError, KeyError) as exc:
            path.unlink()
            raise HTTPException(422, "Invalid CSV: " + str(exc)[:200])
        if not data:
            path.unlink()
            raise HTTPException(422, "CSV must contain bars")
        info = {
            "symbol": body.symbol,
            "timeframe": body.timeframe,
            "source": body.source,
            "path": str(path),
            "bars": len(data),
        }
        store.set_state("dataset:" + body.symbol + ":" + body.timeframe, info)
        store.event("dataset.imported", path.stem, {k: v for k, v in info.items() if k != "path"})
        return info

    @app.post("/api/backtests", dependencies=[Depends(write_access)])
    def backtests(tasks: BackgroundTasks):
        from .backtest import replay
        from .data import read_csv
        from .domain import SymbolSpec

        datasets = {}
        specs = {}
        spread = {}
        rows = store.rows("SELECT value FROM state WHERE key LIKE 'dataset:%'")
        for row in rows:
            d = json.loads(row["value"])
            datasets.setdefault(d["symbol"], {})[d["timeframe"]] = read_csv(
                Path(d["path"]), d["symbol"], d["timeframe"], d["source"]
            )
        primaries = {i.symbol for i in settings.instruments if i.enabled}
        for symbol in set(datasets) & primaries:
            raw = store.state("spec:" + symbol)
            if raw is None:
                raise HTTPException(409, f"Verify MT5 contract specifications for {symbol} before replay")
            specs[symbol] = SymbolSpec.model_validate(raw)
            spread[symbol] = settings.instrument(symbol).max_spread
        if not specs or not all("M1" in datasets[s] for s in specs):
            raise HTTPException(409, "Import M1 execution data and the required strategy timeframes first")
        run_id = str(uuid4())
        created = iso(utcnow())
        with store.transaction() as db:
            if store.state("backtest_running", False, db):
                raise HTTPException(409, "A backtest is already running")
            store.set_state("backtest_running", True, db)

        def work():
            try:
                result = replay(
                    settings,
                    {s: datasets[s] for s in specs},
                    specs,
                    Path("var/backtests") / (run_id + ".db"),
                    spread,
                )
                with store.transaction() as db:
                    db.execute(
                        "INSERT INTO research VALUES(?,?,?,?,?)",
                        (run_id, created, "backtest", settings.policy.digest, encode(result)),
                    )
            except Exception as exc:
                store.event("backtest.failed", run_id, {"error_type": type(exc).__name__})
            finally:
                store.set_state("backtest_running", False)

        tasks.add_task(work)
        return {
            "id": run_id,
            "message": "Replay queued using configured maximum spreads as a conservative cost scenario. Results will appear in Research.",
        }

    @app.post("/api/controls/kill", dependencies=[Depends(write_access)])
    def kill(body: Control):
        store.set_state("kill", body.enabled)
        store.event("control.kill", "system", {"enabled": body.enabled})
        return {
            "kill": body.enabled,
            "effect": "New orders suspended; existing stops and position management remain active.",
        }

    @app.post("/api/controls/reality-check", dependencies=[Depends(write_access)])
    def reality_check():
        now = utcnow()
        store.set_state("reality_confirmed_at", iso(now))
        store.set_state("reality_required", False)
        store.event("control.reality_check", "operator", {"confirmed_at": iso(now)})
        return {"message": "Manual reality check recorded. The 10-minute trade cooldown still applies."}

    @app.post("/api/controls/clear-suspension", dependencies=[Depends(write_access)])
    def clear_suspension():
        if store.rows("SELECT id FROM orders WHERE status IN ('unknown','submitting','reserved','partial')"):
            raise HTTPException(409, "Uncertain or partial execution intents require reconciliation first")
        if settings.mode in ("demo", "live") and not store.state("reconciliation_complete", False):
            raise HTTPException(409, "A complete broker reconciliation is required")
        if not store.verify_chain():
            raise HTTPException(409, "Audit integrity verification failed")
        store.set_state("suspended", False)
        store.event("control.suspension_cleared", "operator", {"operator_confirmed_issue_resolved": True})
        return {
            "message": "Critical-error suspension cleared after operator review; all risk and strategy gates still apply."
        }

    @app.get("/api/export/trades.csv", dependencies=[Depends(read_access)])
    def export():
        stream = io.StringIO()
        fields = [
            "id",
            "signal_id",
            "symbol",
            "direction",
            "mode",
            "status",
            "opened_at",
            "closed_at",
            "entry",
            "exit",
            "volume",
            "net",
            "costs",
            "realized_r",
            "rating",
            "setup",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in trades(store):
            safe = {
                k: ("'" + str(v) if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v)
                for k, v in r.items()
            }
            writer.writerow(safe)
        return StreamingResponse(
            iter([stream.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="msnr-trades.csv"'},
        )

    @app.get("/api/compliance", dependencies=[Depends(read_access)])
    def compliance():
        p = Path("docs/requirements.json")
        return json.loads(p.read_text()) if p.exists() else []

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app
