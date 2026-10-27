"""Serialize native terminal access without queuing abandoned HTTP requests."""

from contextlib import contextmanager
import json
import logging
import threading
import time

from fastapi import HTTPException

from .clock import iso, utcnow
from .market_health import TerminalReadError

log = logging.getLogger("msnr")


class TerminalGate:
    def __init__(self):
        self.lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.active = None
        self.last_completed = None
        self.last_error = None

    def snapshot(self):
        with self.state_lock:
            return {
                "active_call": self.active,
                "last_completed": self.last_completed,
                "last_error": self.last_error,
            }

    @contextmanager
    def call(self, operation, symbol=None, timeframe=None):
        if not self.lock.acquire(blocking=False):
            raise HTTPException(
                503,
                {
                    "code": "mt5_busy",
                    "scope": "connection",
                    "retry_after": 5,
                    "operation": operation,
                    "symbol": symbol,
                    "timeframe": timeframe,
                },
            )
        started = time.monotonic()
        record = {"operation": operation, "symbol": symbol, "timeframe": timeframe, "at": iso(utcnow())}
        with self.state_lock:
            self.active = record
        log.warning(json.dumps({"event": "mt5.call.started", **record}))
        try:
            yield
        except TerminalReadError as exc:
            with self.state_lock:
                self.last_error = {**record, **exc.details}
            log.warning(json.dumps({"event": "mt5.call.failed", **self.last_error}))
            raise HTTPException(503, exc.details) from None
        finally:
            completed = {**record, "elapsed_seconds": round(time.monotonic() - started, 3)}
            with self.state_lock:
                self.active = None
                self.last_completed = completed
            self.lock.release()
            log.warning(json.dumps({"event": "mt5.call.completed", **completed}))
