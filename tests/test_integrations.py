from datetime import timedelta
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from msnr.api import create_app
from msnr.clock import period, quarter, UTC
from msnr.integrations.discord import Discord, signal_embed
from msnr.integrations.mt5 import MT5Bridge
from msnr.reports import schedule_reports
from msnr.charts import render
from msnr.analytics import summarize, monte_carlo
from msnr.backtest import replay, walk_forward_windows
from conftest import NOW, candle


def test_discord_rate_limit_and_duplicate(store):
    attempts = []

    def respond(request):
        attempts.append(request)
        return (
            httpx.Response(429, json={"retry_after": 2})
            if len(attempts) == 1
            else httpx.Response(200, json={"id": "123"})
        )

    d = Discord(
        store,
        "https://discord.com/api/webhooks/test/not-a-real-token",
        httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert store.enqueue("stable-key", {"summary": "Test only"}, NOW)
    assert not store.enqueue("stable-key", {"summary": "Test only"}, NOW)
    assert d.deliver_one(NOW)["status"] == "pending"
    assert d.deliver_one(NOW + timedelta(seconds=1)) is None
    assert d.deliver_one(NOW + timedelta(seconds=2))["status"] == "sent"
    assert d.deliver_one(NOW + timedelta(seconds=10)) is None


def test_discord_unknown_not_retried(store):
    def fail(request):
        raise httpx.ReadTimeout("fixture", request=request)

    store.enqueue("uncertain", {"summary": "Test only"}, NOW)
    d = Discord(
        store,
        "https://discord.com/api/webhooks/test/not-a-real-token",
        httpx.Client(transport=httpx.MockTransport(fail)),
    )
    assert d.deliver_one(NOW)["status"] == "unknown"
    assert d.deliver_one(NOW + timedelta(days=1)) is None


def test_webhook_rejects_untrusted_host(store):
    with pytest.raises(ValueError):
        Discord(store, "http://localhost/api/webhooks/a/b")


def test_report_boundaries_and_restart(store):
    a, b = period(NOW, "daily")
    assert a.hour == 21 and b.hour == 21 and b - a == timedelta(days=1)
    a, b = period(NOW, "weekly")
    assert b.weekday() == 4 and b.hour == 21 and b - a == timedelta(days=7)
    assert len(schedule_reports(store, NOW, 100000)) == 2
    assert schedule_reports(store, NOW, 100000) == []
    assert len(store.rows("SELECT * FROM outbox")) == 2


def test_ny_dst_cycle():
    from datetime import datetime

    # 09:00 local is Q3 in both seasons, at different UTC hours.
    assert quarter(datetime(2026, 7, 1, 13, tzinfo=UTC)) == 3
    assert quarter(datetime(2026, 1, 1, 14, tzinfo=UTC)) == 3


def test_chart_has_only_observable_broker_data(signal, tmp_path):
    bs = [
        candle(-3, 99, 102, 98, 100),
        candle(-2, 100, 103, 99, 102),
        candle(-1, 102, 103, 99, 100),
        candle(0, 100, 999, 1, 100),
    ]
    path = render(signal, bs, tmp_path)
    assert path.stat().st_size > 10000
    manifest = json.loads(path.with_suffix(".json").read_text())
    assert len(manifest["bars"]) == 3
    assert all(b["high"] < 999 for b in manifest["bars"])
    assert signal_embed(signal)["allowed_mentions"] == {"parse": []}


def test_api_auth_kill_journal_csv(settings, store, monkeypatch):
    monkeypatch.setenv("MSNR_OPERATOR_TOKEN", "test-only-token-" + "x" * 32)
    client = TestClient(create_app(settings, store))
    assert client.get("/health").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/controls/kill", json={"enabled": True}).status_code == 401
    assert client.post("/api/login", json={"token": "test-only-token-" + "x" * 32}).status_code == 200
    assert client.get("/api/status").json()["mode"] == "paper"
    assert client.post("/api/controls/kill", json={"enabled": True}).json()["kill"] is True
    assert store.state("kill") is True
    assert client.post("/api/journal", json={"entity_id": "test", "note": "Review"}).status_code == 200
    assert client.get("/api/export/trades.csv").text.startswith("id,signal_id")
    assert (
        client.post(
            "/api/controls/kill", json={"enabled": False}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_api_empty_metrics_are_not_fabricated(settings, store):
    client = TestClient(create_app(settings, store))
    data = client.get("/api/analytics").json()
    assert data["closed_trades"] == 0 and data["win_rate"] is None and data["profit_factor"] is None
    assert "No verified" not in client.get("/api/status").text  # JSON uses null, not made-up balances.
    assert client.get("/api/status").json()["account"] is None
    assert client.get("/").status_code == 200


def test_api_unavailable_database_fails_health(settings, store, monkeypatch):
    client = TestClient(create_app(settings, store))

    def fail(*args):
        raise OSError("fixture")

    monkeypatch.setattr(store, "rows", fail)
    assert client.get("/health").status_code == 503


def test_mt5_requires_secure_bridge():
    with pytest.raises(ValueError):
        MT5Bridge("http://remote.example", token="test")
    with pytest.raises(ValueError):
        MT5Bridge("https://user:pass@remote.example", token="test")


def test_insufficient_statistics_not_claimed():
    assert monte_carlo([1, -1] * 5)["status"] == "insufficient_sample"
    assert summarize([])["expectancy"] is None


def test_walk_forward_has_embargo():
    times = [NOW + timedelta(days=i) for i in range(20)]
    windows = walk_forward_windows(times, 8, 3, 1)
    assert windows and all(w["train"][1] < w["test"][0] - timedelta(hours=12) for w in windows)


def test_empty_replay_is_not_validation(settings, spec, tmp_path):
    bs = [candle(i, 100, 101, 99, 100, tf="M1", minutes=1) for i in range(4)]
    result = replay(
        settings, {"XAUUSDm": {"M1": bs}}, {"XAUUSDm": spec}, tmp_path / "replay.db", {"XAUUSDm": 0.1}
    )
    assert result["evaluations"] == 4
    assert result["status"] == "no_completed_trades_not_strategy_validation"
