from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import os
import threading
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import Field

from .clock import iso, utcnow
from .domain import Model
from .integrations.mt5 import Terminal
from .store import Store, encode


class OrderRequest(Model):
    command_id: UUID
    account_id: str
    symbol: str
    direction: str
    volume: float = Field(gt=0)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)
    signal_id: UUID
    policy_hash: str


class ModifyRequest(Model):
    command_id: UUID
    ticket: int = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)


class CloseRequest(Model):
    command_id: UUID
    ticket: int = Field(gt=0)
    volume: float = Field(gt=0)


def create_bridge(terminal=None, db_path="var/bridge.db"):
    terminal = terminal or Terminal()
    store = Store(db_path)
    lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(app):
        terminal.connect()
        yield
        terminal.mt.shutdown()

    def auth(authorization: str = Header(default="")):
        token = os.getenv("MSNR_BRIDGE_TOKEN", "")
        if len(token) < 32 or not hmac.compare_digest(authorization, "Bearer " + token):
            raise HTTPException(401, "Bridge authentication required")

    app = FastAPI(title="MSnR Windows MT5 Bridge", dependencies=[Depends(auth)], lifespan=lifespan)

    def permit():
        a = terminal.account()
        if not a["trading_allowed"]:
            raise HTTPException(409, "Terminal trading permission unavailable")
        if not a.get("hedging"):
            raise HTTPException(
                409,
                "Independent strategy positions require a hedging account; netting accounts are not enabled",
            )
        if a["mode"] == "real" and os.getenv("MSNR_BRIDGE_ALLOW_LIVE") != "EXPLICITLY_AUTHORIZED":
            raise HTTPException(403, "Live bridge execution disabled")
        return a

    def command(command_id, request):
        key = "command:" + str(command_id)
        with store.transaction() as db:
            old = store.state(key, None, db)
            if old:
                if old.get("request_hash") != encode(request):
                    raise HTTPException(409, "Command ID reused with different parameters")
                return old
            pending = {"status": "unknown", "request_hash": encode(request), "at": iso(utcnow())}
            store.set_state(key, pending, db)
            store.event("bridge.command_intent", str(command_id), request, db=db)
        result = terminal.mt.order_send(request)
        if result is None:
            return pending
        status = (
            "filled"
            if result.retcode == terminal.mt.TRADE_RETCODE_DONE
            else "partial"
            if result.retcode == terminal.mt.TRADE_RETCODE_DONE_PARTIAL
            else "rejected"
        )
        response = {
            "status": status,
            "ticket": int(result.order),
            "deal": int(result.deal),
            "volume": result.volume,
            "price": result.price,
            "retcode": result.retcode,
            "request_hash": encode(request),
        }
        store.set_state(key, response)
        store.event(
            "bridge.command_result",
            str(command_id),
            {k: v for k, v in response.items() if k != "request_hash"},
        )
        return response

    @app.get("/account")
    def account():
        with lock:
            return terminal.account()

    @app.get("/symbols")
    def symbols():
        with lock:
            return terminal.symbols()

    @app.get("/quote")
    def quote(symbol: str):
        with lock:
            return terminal.quote(symbol)

    @app.get("/spec")
    def spec(symbol: str):
        with lock:
            return terminal.spec(symbol)

    @app.get("/bars")
    def bars(symbol: str, timeframe: str, count: int = 1000):
        if not 1 <= count <= 10000:
            raise HTTPException(422, "count must be 1–10000")
        with lock:
            return terminal.bars(symbol, timeframe, count)

    @app.get("/reconcile")
    def reconcile():
        with lock:
            return terminal.reconcile()

    @app.get("/commands/{command_id}")
    def command_status(command_id: UUID):
        with lock:
            return store.state("command:" + str(command_id), {"status": "not_found"})

    @app.post("/orders")
    def place(body: OrderRequest):
        with lock:
            a = permit()
            if a["id"] != body.account_id:
                raise HTTPException(409, "Account identity changed")
            if body.direction not in ("BUY", "SELL"):
                raise HTTPException(422, "Invalid direction")
            spec = terminal.spec(body.symbol)
            q = terminal.quote(body.symbol)
            sign = 1 if body.direction == "BUY" else -1
            price = q.ask if sign == 1 else q.bid
            if not spec.trade_allowed or not spec.market_open:
                raise HTTPException(409, "Market unavailable")
            if (
                not spec.volume_min <= body.volume <= spec.volume_max
                or abs(body.volume / spec.volume_step - round(body.volume / spec.volume_step)) > 1e-6
            ):
                raise HTTPException(422, "Broker lot constraints violated")
            if (price - body.stop) * sign <= spec.stops_distance or (
                body.target - price
            ) * sign <= spec.stops_distance:
                raise HTTPException(422, "Invalid SL/TP geometry")
            if abs(price - body.entry) > 5 * spec.tick_size:
                raise HTTPException(409, "Quote moved beyond permitted slippage")
            mt = terminal.mt
            mode = next(iter(spec.filling_modes), None)
            if mode is None:
                raise HTTPException(409, "No supported filling mode")
            request = {
                "action": mt.TRADE_ACTION_DEAL,
                "symbol": body.symbol,
                "volume": body.volume,
                "type": mt.ORDER_TYPE_BUY if sign == 1 else mt.ORDER_TYPE_SELL,
                "price": price,
                "sl": body.stop,
                "tp": body.target,
                "deviation": max(0, int(5 * spec.tick_size / spec.point)),
                "magic": int(body.command_id.hex[:7], 16),
                "comment": "msnr:" + body.command_id.hex[:20],
                "type_time": mt.ORDER_TIME_GTC,
                "type_filling": getattr(mt, "ORDER_FILLING_" + mode),
            }
            checked = mt.order_check(request)
            if checked is None or checked.retcode != 0:
                return {"status": "rejected", "retcode": checked.retcode if checked else None}
            return command(body.command_id, request)

    @app.post("/positions/modify")
    def modify(body: ModifyRequest):
        with lock:
            permit()
            mt = terminal.mt
            positions = mt.positions_get(ticket=body.ticket)
            if not positions:
                raise HTTPException(404, "Position unavailable")
            p = positions[0]
            sign = 1 if p.type == mt.POSITION_TYPE_BUY else -1
            if p.sl and (body.stop - p.sl) * sign < 0:
                raise HTTPException(422, "Stop widening prohibited")
            return command(
                body.command_id,
                {
                    "action": mt.TRADE_ACTION_SLTP,
                    "position": body.ticket,
                    "symbol": p.symbol,
                    "sl": body.stop,
                    "tp": body.target,
                },
            )

    @app.post("/positions/close")
    def close(body: CloseRequest):
        with lock:
            permit()
            mt = terminal.mt
            positions = mt.positions_get(ticket=body.ticket)
            if not positions:
                raise HTTPException(404, "Position unavailable")
            p = positions[0]
            spec = terminal.spec(p.symbol)
            q = terminal.quote(p.symbol)
            if (
                body.volume > p.volume
                or body.volume < spec.volume_min
                or abs(body.volume / spec.volume_step - round(body.volume / spec.volume_step)) > 1e-6
            ):
                raise HTTPException(422, "Invalid close volume")
            buy = p.type == mt.POSITION_TYPE_BUY
            return command(
                body.command_id,
                {
                    "action": mt.TRADE_ACTION_DEAL,
                    "position": body.ticket,
                    "symbol": p.symbol,
                    "volume": body.volume,
                    "type": mt.ORDER_TYPE_SELL if buy else mt.ORDER_TYPE_BUY,
                    "price": q.bid if buy else q.ask,
                    "deviation": 5,
                    "type_filling": getattr(mt, "ORDER_FILLING_" + spec.filling_modes[0]),
                },
            )

    return app
