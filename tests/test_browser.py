"""Real Chrome E2E. Requires MSNR_CHROME_EXECUTABLE; no broker or Discord calls."""

import os
from pathlib import Path
import socket
import subprocess
import time

import httpx
import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope="module")
def browser_server(tmp_path_factory):
    chrome = os.getenv("MSNR_CHROME_EXECUTABLE")
    if not chrome or not Path(chrome).is_file():
        pytest.skip("Set MSNR_CHROME_EXECUTABLE to run real Chrome end-to-end validation")
    temporary = tmp_path_factory.mktemp("browser")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = "browser-test-only-" + "a" * 32
    env = {**os.environ, "MSNR_OPERATOR_TOKEN": token, "MSNR_DB": str(temporary / "browser.db")}
    log = (temporary / "server.log").open("w")
    process = subprocess.Popen(
        [
            str(Path(".venv/bin/python").absolute()),
            "-m",
            "msnr.cli",
            "--db",
            str(temporary / "browser.db"),
            "serve",
            "--port",
            str(port),
        ],
        env=env,
        stdout=log,
        stderr=log,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/health").status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("Browser test server did not start")
    yield base, token, chrome
    process.terminate()
    process.wait(timeout=10)
    log.close()


def test_chrome_navigation_controls_and_reflow(browser_server):
    base, token, chrome = browser_server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base)
        page.get_by_label("Operator token", exact=True).fill(token)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.get_by_role("heading", name="The path to a trade").wait_for()
        assert page.locator("#error").is_hidden()
        page.get_by_role("button", name="Suspend execution").click()
        page.get_by_role("button", name="Resume new execution").wait_for()
        for name in (
            "Live signals",
            "Trades",
            "Trading journal",
            "Analytics",
            "Backtesting",
            "Reports",
            "Settings",
            "Overview",
        ):
            page.get_by_role("navigation").get_by_role("link", name=name, exact=False).click()
            expect(page.locator("#content")).not_to_have_attribute("aria-busy", "true")
            assert page.locator("#error").is_hidden(), name
        axe = Path("node_modules/axe-core/axe.min.js")
        if axe.exists():
            page.route(
                "**/__axe-test.js",
                lambda route: route.fulfill(content_type="application/javascript", body=axe.read_text()),
            )
            page.add_script_tag(url=base + "/__axe-test.js")
            audit = page.evaluate(
                "async () => await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
            )
            assert not audit["violations"], [
                (v["id"], [(n["target"], n.get("failureSummary")) for n in v["nodes"]])
                for v in audit["violations"]
            ]
            Path("artifacts").mkdir(exist_ok=True)
            import json

            Path("artifacts/accessibility.json").write_text(
                json.dumps(
                    {
                        "violations": audit["violations"],
                        "passes": len(audit["passes"]),
                        "incomplete": len(audit["incomplete"]),
                    },
                    indent=2,
                )
            )
        page.keyboard.press("Tab")
        assert page.locator(":focus").count() == 1
        Path("artifacts").mkdir(exist_ok=True)
        page.screenshot(path="artifacts/dashboard-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path="artifacts/dashboard-mobile.png", full_page=True)
        assert not errors
        browser.close()


def test_native_chart_anchor_readback_and_failure_cleanup(browser_server, signal):
    from msnr.integrations.tradingview import DRAW, CAPABILITY, drawing_plan

    _, _, chrome = browser_server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, headless=True)
        page = browser.new_page()
        page.set_content("<title>Local native-chart API test double</title>")
        assert not page.evaluate(CAPABILITY)["available"]
        page.evaluate("""() => {
          window.objects = new Map(); window.counter = 0; window.offset = 0;
          window.chart = {
            symbol: () => 'TEST:XAUUSD', resolution: () => '5',
            createShape: (point) => {let id = ++window.counter; objects.set(id,[point]); return id;},
            getShapeById: id => ({getPoints: () => objects.get(id).map(p => ({...p, price:p.price+offset}))}),
            removeEntity: id => objects.delete(id),
            getVisibleRange: () => ({from:100, to:1000}), setVisibleRange: async r => r
          };
          window.TradingViewApi = {activeChart: () => chart};
        }""")
        args = {"symbol": "TEST:XAUUSD", "resolution": "5", "commands": drawing_plan(signal)}
        assert page.evaluate(DRAW, args)["verified"]
        count = page.evaluate("objects.size")
        assert not page.evaluate(DRAW, {**args, "symbol": "WRONG"})["verified"]
        assert page.evaluate("objects.size") == count
        page.evaluate("window.offset = 1")
        assert not page.evaluate(DRAW, args)["verified"]
        assert page.evaluate("objects.size") == count  # only newly created shapes cleaned up
        browser.close()
