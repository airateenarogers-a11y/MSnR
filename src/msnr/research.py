"""Reproducible research orchestration. Never changes or activates a trading rule."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import json

from .backtest import replay, walk_forward_windows
from .config import Settings


def validate(settings: Settings, datasets, specs, spread, directory: Path, train_fraction=0.7, folds=3):
    if not 0.5 <= train_fraction <= 0.9 or not 2 <= folds <= 10:
        raise ValueError("Declare a 50–90% training split and 2–10 folds before research")
    times = sorted({b.time for f in datasets.values() for b in f.get("M1", [])})
    if len(times) < 100:
        raise ValueError(
            "At least 100 execution bars required to separate temporal windows; this is not a trade sample sufficiency claim"
        )
    if directory.exists():
        raise ValueError("Research output directory must be new")
    directory.mkdir(parents=True)
    split = int(len(times) * train_fraction)
    embargo = 1
    inside = replay(
        settings, datasets, specs, directory / "in_sample.db", spread, start=times[0], end=times[split]
    )
    outside = replay(
        settings,
        datasets,
        specs,
        directory / "out_of_sample.db",
        spread,
        start=times[split + embargo],
        end=times[-1] + timedelta(minutes=1),
    )
    test = max(1, (len(times) - split - embargo) // folds)
    windows = walk_forward_windows(times, split, test, embargo)
    forward = []
    for i, window in enumerate(windows):
        r = replay(
            settings,
            datasets,
            specs,
            directory / f"walk-{i}.db",
            spread,
            start=window["test"][0],
            end=window["test"][1] + timedelta(minutes=1),
        )
        forward.append(
            {
                "window": {k: str(v) for k, v in window.items()},
                "closed_trades": r["closed_trades"],
                "expectancy": r["expectancy"],
                "sample_sufficient": r["sample_sufficient"],
                "net": r["closed_net"],
            }
        )
    sensitivity = []
    for multiplier in (0.5, 1.0, 2.0):
        altered = settings.model_copy(
            update={
                "risk": settings.risk.model_copy(
                    update={"commission_per_lot": settings.risk.commission_per_lot * multiplier}
                )
            }
        )
        r = replay(
            altered,
            datasets,
            specs,
            directory / f"cost-{multiplier}.db",
            {s: v * multiplier for s, v in spread.items()},
            start=times[split + embargo],
            end=times[-1] + timedelta(minutes=1),
        )
        sensitivity.append(
            {
                "execution_cost_multiplier": multiplier,
                "net": r["closed_net"],
                "closed_trades": r["closed_trades"],
            }
        )
    measured = [r["expectancy"] for r in forward if r["expectancy"] is not None]
    result = {
        "policy_hash": settings.policy.digest,
        "strategy_parameters_changed": False,
        "in_sample": inside,
        "out_of_sample": outside,
        "walk_forward": forward,
        "cost_sensitivity": sensitivity,
        "overfitting_warning": bool(
            inside["expectancy"] is not None
            and outside["expectancy"] is not None
            and inside["expectancy"] > 0 >= outside["expectancy"]
        ),
        "positive_window_fraction": sum(x > 0 for x in measured) / len(measured) if measured else None,
        "credible_edge_established": False,
        "approval_required_for_strategy_changes": True,
        "limitations": [
            "No parameter optimization is performed; windows audit one fixed approved policy.",
            "Minimum sample counts and positive historical results are insufficient for production authorization.",
            "Forward broker performance is unavailable until measured on a connected demo account.",
        ],
    }
    (directory / "validation.json").write_text(json.dumps(result, indent=2))
    return result
