from __future__ import annotations

from datetime import datetime
import os
from urllib.parse import urlsplit

import httpx

from ..clock import UTC
from ..domain import Bar, Quote, SymbolSpec


class MT5Bridge:
    def __init__(self, base_url: str | None = None, token: str | None = None, client=None):
        url = base_url or os.getenv("MSNR_BRIDGE_URL", "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise ValueError("MT5 bridge requires HTTPS, except loopback development")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Credentials must not be present in a URL")
        credential = token or os.getenv("MSNR_BRIDGE_TOKEN")
        if not credential:
            raise ValueError("MSNR_BRIDGE_TOKEN is required")
        self.client = client or httpx.Client(
            base_url=url,
            headers={"Authorization": "Bearer " + credential},
            timeout=15,
            follow_redirects=False,
        )

    def get(self, path, **params):
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def symbols(self):
        return self.get("/symbols")

    def account(self):
        return self.get("/account")

    def quote(self, symbol):
        return Quote.model_validate(self.get("/quote", symbol=symbol))

    def spec(self, symbol):
        return SymbolSpec.model_validate(self.get("/spec", symbol=symbol))

    def bars(self, symbol, timeframe, count=1000):
        return [
            Bar.model_validate(b) for b in self.get("/bars", symbol=symbol, timeframe=timeframe, count=count)
        ]

    def reconcile(self):
        return self.get("/reconcile")

    def command_status(self, command_id):
        return self.get("/commands/" + command_id)

    def place(self, command_id, signal, decision, spec, account_id):
        response = self.client.post(
            "/orders",
            json={
                "command_id": command_id,
                "account_id": account_id,
                "symbol": signal.symbol,
                "direction": signal.direction,
                "volume": decision.volume,
                "entry": signal.entry,
                "stop": signal.stop,
                "target": signal.targets[-1],
                "signal_id": signal.id,
                "policy_hash": signal.policy_hash,
            },
        )
        response.raise_for_status()
        return response.json()

    def modify(self, command_id, ticket, stop, target):
        response = self.client.post(
            "/positions/modify",
            json={"command_id": command_id, "ticket": ticket, "stop": stop, "target": target},
        )
        response.raise_for_status()
        return response.json()

    def close_position(self, command_id, ticket, volume):
        response = self.client.post(
            "/positions/close", json={"command_id": command_id, "ticket": ticket, "volume": volume}
        )
        response.raise_for_status()
        return response.json()

    def close(self):
        self.client.close()


class Terminal:
    """Official Windows MT5 API, imported only on a configured Windows host."""

    def __init__(self, module=None):
        if module is None:
            if os.name != "nt":
                raise RuntimeError(
                    "The official MT5 Python terminal requires Windows; use the HTTPS bridge on Linux"
                )
            import MetaTrader5 as module
        self.mt = module

    def connect(self):
        args = {}
        for env, key, cast in [
            ("MT5_TERMINAL_PATH", "path", str),
            ("MT5_LOGIN", "login", int),
            ("MT5_PASSWORD", "password", str),
            ("MT5_SERVER", "server", str),
        ]:
            if os.getenv(env):
                args[key] = cast(os.environ[env])
        if not self.mt.initialize(**args):
            raise RuntimeError("MT5 initialize failed; check terminal connection and local credentials")

    def account(self):
        a = self.mt.account_info()
        t = self.mt.terminal_info()
        if a is None or t is None or not t.connected:
            raise RuntimeError("MT5 account disconnected")
        return {
            "id": str(a.login),
            "mode": "demo" if a.trade_mode == self.mt.ACCOUNT_TRADE_MODE_DEMO else "real",
            "balance": a.balance,
            "equity": a.equity,
            "free_margin": a.margin_free,
            "currency": a.currency,
            "trading_allowed": bool(a.trade_allowed and a.trade_expert and t.trade_allowed),
            "at": datetime.now(UTC).isoformat(),
            "hedging": a.margin_mode == self.mt.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
        }

    def symbols(self):
        values = self.mt.symbols_get()
        if values is None:
            raise RuntimeError("MT5 symbol discovery failed")
        return [{"symbol": s.name, "description": s.description, "trade_mode": s.trade_mode} for s in values]

    def quote(self, symbol):
        if not self.mt.symbol_select(symbol, True):
            raise ValueError("Exact broker symbol unavailable")
        q = self.mt.symbol_info_tick(symbol)
        if q is None:
            raise RuntimeError("MT5 quote unavailable")
        return Quote(symbol=symbol, time=datetime.fromtimestamp(q.time_msc / 1000, UTC), bid=q.bid, ask=q.ask)

    def spec(self, symbol):
        q = self.quote(symbol)
        s = self.mt.symbol_info(symbol)
        a = self.account()
        modes = []
        if s.filling_mode & 1:
            modes.append("FOK")
        if s.filling_mode & 2:
            modes.append("IOC")
        # RETURN is not allowed for Market Execution instruments.
        if s.trade_exemode != self.mt.SYMBOL_TRADE_EXECUTION_MARKET:
            modes.append("RETURN")
        return SymbolSpec(
            symbol=symbol,
            tick_size=s.trade_tick_size,
            tick_value_loss=s.trade_tick_value_loss,
            point=s.point,
            volume_min=s.volume_min,
            volume_max=s.volume_max,
            volume_step=s.volume_step,
            stops_distance=s.trade_stops_level * s.point,
            freeze_distance=s.trade_freeze_level * s.point,
            contract_size=s.trade_contract_size,
            trade_allowed=s.trade_mode == self.mt.SYMBOL_TRADE_MODE_FULL,
            market_open=0 <= (datetime.now(UTC) - q.time).total_seconds() < 15,
            currency_profit=s.currency_profit,
            currency_account=a["currency"],
            filling_modes=tuple(modes),
        )

    def bars(self, symbol, timeframe, count):
        from ..data import end_time, TIMEFRAMES

        if timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported timeframe")
        self.quote(symbol)
        rates = self.mt.copy_rates_from_pos(symbol, getattr(self.mt, "TIMEFRAME_" + timeframe), 0, count)
        if rates is None:
            raise RuntimeError("MT5 history retrieval failed")
        return [
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                time=datetime.fromtimestamp(int(r["time"]), UTC),
                end=end_time(datetime.fromtimestamp(int(r["time"]), UTC), timeframe),
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=float(r["tick_volume"]),
                source="MT5:" + symbol,
            )
            for r in rates
        ]

    def reconcile(self):
        positions = self.mt.positions_get()
        orders = self.mt.orders_get()
        now = datetime.now(UTC)
        deals = self.mt.history_deals_get(datetime(2020, 1, 1, tzinfo=UTC), now)
        if positions is None or orders is None or deals is None:
            return {"complete": False, "at": now.isoformat()}
        return {
            "complete": True,
            "at": now.isoformat(),
            "account": self.account(),
            "positions": [p._asdict() for p in positions],
            "orders": [o._asdict() for o in orders],
            "deals": [d._asdict() for d in deals],
        }
