from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import os

os.environ.setdefault("MPLCONFIGDIR", str(Path("var/cache/matplotlib").absolute()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("var/cache").absolute()))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from .domain import Bar, Signal


def render(signal: Signal, bars: list[Bar], directory: Path) -> Path:
    usable = [
        b
        for b in bars
        if b.symbol == signal.symbol and b.timeframe == signal.timeframe and b.end <= signal.created_at
    ]
    if not usable or any(b.source != signal.data_source for b in usable):
        raise ValueError("No matching observable broker data for this signal")
    usable = usable[-100:]
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (signal.id + ".png")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
    fig.set_facecolor("#0c1217")
    ax.set_facecolor("#101b22")
    ax.tick_params(colors="#a9b9c2")
    ax.grid(color="#28363e", linewidth=0.5, alpha=0.6)
    for spine in ax.spines.values():
        spine.set_color("#28363e")
    x = mdates.date2num([b.time for b in usable])
    width = (x[-1] - x[0]) / max(len(x) - 1, 1) * 0.65 or 0.0004
    for t, b in zip(x, usable):
        color = "#66d5ba" if b.close >= b.open else "#f39185"
        ax.vlines(t, b.low, b.high, color=color, linewidth=1)
        ax.add_patch(
            Rectangle(
                (t - width / 2, min(b.open, b.close)),
                width,
                max(abs(b.close - b.open), b.close * 1e-8),
                color=color,
            )
        )
    annotations = [("ENTRY", signal.entry, "#e6c88b"), ("STOP / INVALIDATION", signal.stop, "#f39185")]
    annotations += [
        (f"TP {i + 1} · {rr:.2f}R", target, "#66d5ba")
        for i, (target, rr) in enumerate(zip(signal.targets, signal.rr))
    ]
    for label, price, color in annotations:
        ax.axhline(price, color=color, linewidth=0.9, linestyle="--")
        ax.annotate(
            f" {label}  {price:,.5f}".rstrip("0").rstrip("."),
            xy=(1, price),
            xycoords=("axes fraction", "data"),
            xytext=(6, 0),
            textcoords="offset points",
            color=color,
            fontsize=9,
            va="center",
        )
    for feature in getattr(signal, "chart_features", ()):
        if "price" not in feature or "time" not in feature:
            continue
        from datetime import datetime

        t = mdates.date2num(datetime.fromisoformat(feature["time"]))
        if x[0] <= t <= x[-1]:
            ax.scatter([t], [feature["price"]], s=18, color="#bac9d7")
            ax.annotate(
                feature["label"],
                (t, feature["price"]),
                xytext=(0, 12),
                textcoords="offset points",
                fontsize=8,
                color="#bac9d7",
                ha="center",
            )
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M UTC"))
    ax.set_title(
        f"{signal.symbol}  /  {signal.direction}  /  {signal.setup}",
        loc="left",
        color="#eff5f7",
        fontsize=19,
        pad=24,
    )
    fig.text(
        0.07,
        0.91,
        f"{signal.htf} storyline → {signal.timeframe} confirmation    •    {signal.rating} / measured confluence, not probability",
        color="#a9b9c2",
    )
    fig.text(0.07, 0.06, signal.reason[:180], color="#a9b9c2", fontsize=9)
    fig.text(
        0.07,
        0.025,
        f"{signal.id}   |   Source: {signal.data_source}   |   As of {signal.created_at.isoformat()}",
        color="#8da1ad",
        fontsize=8,
    )
    ax.set_xlim(x[0] - width, x[-1] + width * 4)
    fig.subplots_adjust(left=0.07, right=0.76, bottom=0.17, top=0.84)
    fig.savefig(destination, facecolor=fig.get_facecolor())
    plt.close(fig)
    manifest = {
        "signal_id": signal.id,
        "signal_sha256": sha256(signal.model_dump_json().encode()).hexdigest(),
        "png_sha256": sha256(destination.read_bytes()).hexdigest(),
        "source": signal.data_source,
        "bars": [b.model_dump(mode="json") for b in usable],
        "annotations": annotations,
        "coordinates": "UTC timestamps and broker prices; Matplotlib data transforms",
        "renderer": "deterministic broker chart; not a TradingView screenshot",
    }
    destination.with_suffix(".json").write_text(json.dumps(manifest, indent=2))
    return destination


def equity_chart(points: list[dict], destination: Path):
    fig, ax = plt.subplots(figsize=(9, 4), dpi=120)
    if points:
        ax.plot([p["equity"] for p in points], color="#167e68")
        ax.set_ylabel("Net realized equity (account currency)")
        ax.set_xlabel("Chronological exit events")
    else:
        ax.text(0.5, 0.5, "No verified outcomes", ha="center", va="center", transform=ax.transAxes)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination)
    plt.close(fig)
