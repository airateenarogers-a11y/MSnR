"""Read-only feed failures, kept separate from uncertain execution outcomes."""


class MarketDataUnavailable(RuntimeError):
    def __init__(
        self,
        operation,
        *,
        code="unavailable",
        symbol=None,
        timeframe=None,
        native_code=None,
        scope="connection",
        retry_after=15,
    ):
        self.details = {
            "operation": operation,
            "code": code,
            "symbol": symbol,
            "timeframe": timeframe,
            "native_code": native_code,
            "scope": scope,
            "retry_after": retry_after,
        }
        context = " / ".join(str(v) for v in (operation, symbol, timeframe) if v)
        super().__init__(f"{context}: {code}" + (f" (MT5 {native_code})" if native_code is not None else ""))


class TerminalReadError(MarketDataUnavailable):
    pass
