from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import load, secret_status
from .store import Store


def main():
    parser = argparse.ArgumentParser(prog="msnr")
    parser.add_argument("--config", default=os.getenv("MSNR_CONFIG", "config/default.json"))
    parser.add_argument("--db", default=os.getenv("MSNR_DB", "var/msnr.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    worker = commands.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    commands.add_parser("doctor")
    commands.add_parser("migrate")
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    tv = commands.add_parser("tradingview-check")
    tv.add_argument("--chrome", default=os.getenv("MSNR_CHROME_EXECUTABLE"))
    tv.add_argument("--output", type=Path, default=Path("artifacts/tradingview"))
    draw = commands.add_parser("tradingview-draw")
    draw.add_argument("signal_id")
    draw.add_argument("--symbol", required=True, help="Exact TradingView symbol, including exchange prefix")
    draw.add_argument("--cdp", default="http://127.0.0.1:9222")
    bridge = commands.add_parser("bridge")
    bridge.add_argument("--host", default="127.0.0.1")
    bridge.add_argument("--port", type=int, default=8765)
    replay_parser = commands.add_parser("backtest")
    replay_parser.add_argument("manifest", type=Path)
    replay_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = load(args.config)
    if args.command == "bridge":
        import uvicorn
        from .bridge import create_bridge

        if len(os.getenv("MSNR_BRIDGE_TOKEN", "")) < 32:
            parser.error("Set a bridge token of at least 32 characters")
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            parser.error("Bridge must bind loopback; expose through an authenticated TLS reverse proxy")
        uvicorn.run(create_bridge(), host=args.host, port=args.port)
        return
    store = Store(args.db)
    if args.command == "serve":
        import uvicorn
        from .api import create_app

        if (
            args.host not in ("127.0.0.1", "localhost", "::1")
            and len(os.getenv("MSNR_OPERATOR_TOKEN", "")) < 32
        ):
            parser.error("Remote binding requires an operator token of at least 32 characters and TLS proxy")
        uvicorn.run(create_app(settings, store), host=args.host, port=args.port, access_log=False)
    elif args.command == "worker":
        from .worker import Worker

        w = Worker(store, settings)
        if args.once:
            try:
                w.once()
            finally:
                w.close()
        else:
            w.run()
    elif args.command == "doctor":
        print(
            json.dumps(
                {
                    "database": args.db,
                    "journal_integrity": store.verify_chain(),
                    "mode": settings.mode,
                    "policy_hash": settings.policy.digest,
                    "credentials_present": secret_status(),
                    "worker": store.state("worker_health", None),
                    "source_version": settings.policy.version,
                    "platform_requirements": {
                        "MT5": "Windows terminal + authenticated bridge",
                        "charts": "Deterministic renderer; Chrome needed for TradingView inspection",
                    },
                },
                indent=2,
            )
        )
    elif args.command == "backup":
        store.backup(args.destination)
        print("Consistent SQLite backup written to " + str(args.destination))
    elif args.command == "tradingview-check":
        from .integrations.tradingview import TradingView

        print(
            json.dumps(
                TradingView(
                    Path(os.getenv("MSNR_TRADINGVIEW_PROFILE", "var/browser-profile")), args.chrome
                ).inspect(args.output),
                indent=2,
            )
        )
    elif args.command == "tradingview-draw":
        from .integrations.tradingview import TradingView
        from .domain import Signal

        rows = store.rows("SELECT payload FROM signals WHERE id=?", (args.signal_id,))
        if not rows:
            parser.error("Signal ID is absent from this database")
        signal = Signal.model_validate_json(rows[0]["payload"])
        print(
            json.dumps(
                TradingView(Path("var/browser-profile")).annotate(signal, args.symbol, args.cdp), indent=2
            )
        )
    elif args.command == "backtest":
        from .backtest import replay
        from .data import read_csv
        from .domain import SymbolSpec

        manifest = json.loads(args.manifest.read_text())
        datasets = {}
        specs = {}
        for entry in manifest["datasets"]:
            p = (args.manifest.parent / entry["path"]).resolve()
            datasets.setdefault(entry["symbol"], {})[entry["timeframe"]] = read_csv(
                p, entry["symbol"], entry["timeframe"], entry["source"]
            )
        for symbol, spec in manifest["specifications"].items():
            specs[symbol] = SymbolSpec.model_validate(spec)
        result = replay(settings, datasets, specs, args.output, manifest["spread"])
        args.output.with_suffix(".json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    elif args.command == "migrate":
        print("Schema version 1 installed; journal chain valid: " + str(store.verify_chain()))


if __name__ == "__main__":
    main()
