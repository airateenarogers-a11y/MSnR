from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import os
import time
from urllib.parse import urlsplit

import httpx

from ..clock import UTC
from ..domain import Bar, Quote, SymbolSpec
from ..market_health import MarketDataUnavailable, TerminalReadError

log = logging.getLogger("msnr")


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
            trust_env=parsed.hostname not in ("127.0.0.1", "localhost", "::1"),
        )

    def get(self, path, **params):
        started = time.monotonic()
        operation = path.strip("/")
        # Cold MT5 history synchronization can outlast the old 15-second HTTP
        # deadline. Commands retain their existing timeout and are never retried.
        timeout = httpx.Timeout(90 if path in ("/bars", "/reconcile") else 15, connect=3, pool=3)
        try:
            response = self.client.get(path, params=params, timeout=timeout)
            if response.status_code == 503:
                detail = response.json().get("detail", {})
                if isinstance(detail, dict):
                    allowed = {
                        k: detail[k]
                        for k in ("code", "symbol", "timeframe", "native_code", "scope", "retry_after")
                        if k in detail
                    }
                    allowed.setdefault("symbol", params.get("symbol"))
                    allowed.setdefault("timeframe", params.get("timeframe"))
                    raise MarketDataUnavailable(operation, **allowed)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            failure = MarketDataUnavailable(
                operation,
                code=type(exc).__name__,
                symbol=params.get("symbol"),
                timeframe=params.get("timeframe"),
            )
            log.warning(
                json.dumps(
                    {
                        "event": "mt5.read.failed",
                        **failure.details,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    }
                )
            )
            raise failure from None

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

    def reconcile(self, since=None):
        return self.get("/reconcile", **({"since": since.isoformat()} if since else {}))

    def command_status(self, command_id):
        return self.get("/commands/" + command_id)

    def diagnostics(self):
        return self.get("/diagnostics")

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
        self.history = {}
        self.account_id = None

    def failure(self, operation, *, symbol=None, timeframe=None, code="mt5_unavailable"):
        error = self.mt.last_error()
        native = int(error[0]) if error else None
        # Authentication/IPC failures affect the entire terminal; missing symbol
        # or history data prevents only that instrument from being evaluated.
        scope = (
            "symbol"
            if native in (-2, -4)
            or (native in (1, None) and code in ("symbol_unavailable", "history_not_ready"))
            else "connection"
        )
        raise TerminalReadError(
            operation, code=code, symbol=symbol, timeframe=timeframe, native_code=native, scope=scope
        )

    def select(self, symbol):
        spec = self.mt.symbol_info(symbol)
        if spec is None or (not spec.visible and not self.mt.symbol_select(symbol, True)):
            self.failure("symbol_select", symbol=symbol, code="symbol_unavailable")
        return spec

    def connect(self):
        args = {"timeout": 10000}
        for env, key, cast in [
            ("MT5_TERMINAL_PATH", "path", str),
            ("MT5_LOGIN", "login", int),
            ("MT5_PASSWORD", "password", str),
            ("MT5_SERVER", "server", str),
        ]:
            if os.getenv(env):
                args[key] = cast(os.environ[env])
        if not self.mt.initialize(**args):
            self.failure("initialize")
        self.history.clear()

    def account(self):
        a = self.mt.account_info()
        t = self.mt.terminal_info()
        if a is None or t is None or not t.connected:
            self.failure("account", code="terminal_disconnected")
        if self.account_id != a.login:
            self.history.clear()
            self.account_id = a.login
        return {
            "id": str(a.login),
            "mode": "demo" if a.trade_mode == self.mt.ACCOUNT_TRADE_MODE_DEMO else "real",
            "balance": a.balance,
            "equity": a.equity,
            "free_margin": a.margin_free,
            "currency": a.currency,
            "trading_allowed": bool(
                a.trade_allowed
                and a.trade_expert
                and t.trade_allowed
                and not getattr(t, "tradeapi_disabled", False)
            ),
            "at": datetime.now(UTC).isoformat(),
            "hedging": a.margin_mode == self.mt.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
        }

    def symbols(self):
        values = self.mt.symbols_get()
        if values is None:
            self.failure("symbols_get")
        return [{"symbol": s.name, "description": s.description, "trade_mode": s.trade_mode} for s in values]

    def quote(self, symbol):
        self.select(symbol)
        q = self.mt.symbol_info_tick(symbol)
        if q is None:
            self.failure("symbol_info_tick", symbol=symbol)
        if not q.time_msc or q.bid <= 0 or q.ask <= 0:
            raise TerminalReadError("quote", code="quote_not_ready", symbol=symbol, scope="symbol")
        return Quote(symbol=symbol, time=datetime.fromtimestamp(q.time_msc / 1000, UTC), bid=q.bid, ask=q.ask)

    def spec(self, symbol):
        q = self.quote(symbol)
        s = self.mt.symbol_info(symbol)
        if s is None:
            self.failure("symbol_info", symbol=symbol)
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
        self.select(symbol)
        key = (symbol, timeframe, count)
        cached = self.history.get(key)
        incremental = bool(cached and time.monotonic() - cached[0] < 300 and cached[1])
        requested = min(count, 3) if incremental else count

        def fetch(amount):
            rates = self.mt.copy_rates_from_pos(symbol, getattr(self.mt, "TIMEFRAME_" + timeframe), 0, amount)
            if rates is None or not len(rates):
                self.history.pop(key, None)
                self.failure(
                    "copy_rates_from_pos", symbol=symbol, timeframe=timeframe, code="history_not_ready"
                )
            return rates

        rates = fetch(requested)
        if incremental and datetime.fromtimestamp(int(rates[0]["time"]), UTC) > cached[1][-1].time:
            # More than the tail elapsed: reload the whole requested window.
            incremental = False
            rates = fetch(count)
        result = [
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
        if incremental:
            merged = {b.time: b for b in cached[1]}
            merged.update({b.time: b for b in result})
            result = [merged[t] for t in sorted(merged)][-count:]
        self.history[key] = (cached[0] if incremental else time.monotonic(), result)
        return result

    def reconcile(self, since=None):
        positions = self.mt.positions_get()
        if positions is None:
            self.failure("positions_get")
        orders = self.mt.orders_get()
        if orders is None:
            self.failure("orders_get")
        now = datetime.now(UTC)
        deals = self.mt.history_deals_get(since or now - timedelta(days=1), now)
        if deals is None:
            self.failure("history_deals_get")
        return {
            "complete": True,
            "at": now.isoformat(),
            "account": self.account(),
            "positions": [p._asdict() for p in positions],
            "orders": [o._asdict() for o in orders],
            "deals": [d._asdict() for d in deals],
        }
