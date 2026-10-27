"""Read-only native MT5 probe. Never sends, modifies or closes an order."""

import argparse
import json
from pathlib import Path
import time

from .clock import iso, utcnow
from .config import load
from .integrations.mt5 import Terminal
from .market_health import MarketDataUnavailable


def probe(terminal, instruments, output):
    report = {"at": iso(utcnow()), "read_only": True, "status": "checking", "symbols": []}

    def save(operation, **context):
        report["checking"] = {"operation": operation, **context}
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(output)

    try:
        save("initialize")
        terminal.connect()
        save("account")
        account = terminal.account()
        report["account"] = {k: account[k] for k in ("mode", "hedging", "trading_allowed")}
        report["account"]["connected"] = True
        save("symbols")
        available = {s["symbol"] for s in terminal.symbols()}
        for instrument in instruments:
            matches = [s for s in (instrument.symbol, *instrument.aliases) if s in available]
            symbol = matches[0] if matches else instrument.symbol
            row = {"configured": instrument.symbol, "broker_symbol": symbol}
            report["symbols"].append(row)
            if not matches:
                row["status"] = "symbol_unavailable"
                continue
            started = time.monotonic()
            try:
                save("quote", symbol=symbol)
                quote = terminal.quote(symbol)
                row["quote"] = {
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "at": iso(quote.time),
                    "age_seconds": round((utcnow() - quote.time).total_seconds(), 1),
                }
                save("copy_rates_from_pos", symbol=symbol, timeframe="M1", count=5)
                bars = terminal.bars(symbol, "M1", 5)
                row["history"] = {
                    "timeframe": "M1",
                    "count": len(bars),
                    "latest_bar": iso(bars[-1].time) if bars else None,
                }
                row["status"] = "readable" if bars else "history_unavailable"
            except MarketDataUnavailable as exc:
                row.update(status="unavailable", error=exc.details)
            finally:
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["status"] = "complete"
    except MarketDataUnavailable as exc:
        report.update(status="unavailable", error=exc.details)
    except Exception as exc:
        # Whitelist the error type; native error strings can contain local details.
        report.update(status="error", error={"code": type(exc).__name__})
    finally:
        terminal.mt.shutdown()
        save("finished")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    probe(Terminal(), [i for i in load(args.config).instruments if i.enabled], args.output)


if __name__ == "__main__":
    main()
