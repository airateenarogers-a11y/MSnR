from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from ..charts import render

TARGET = "https://www.tradingview.com/chart/O7UQR2ba/"

CAPABILITY = """() => {
 const c = window.TradingViewApi?.activeChart?.();
 return {available: !!c, symbol: c?.symbol?.(), resolution: c?.resolution?.(),
   writable: !!(c?.createShape && c?.getShapeById && c?.removeEntity),
   viewport: !!(c?.getVisibleRange && c?.setVisibleRange)};
}"""

# Use native time/price coordinates, then read them back before and after a viewport change.
# This API is not guaranteed to exist on every TradingView account/layout.
DRAW = """async ({symbol, resolution, commands}) => {
 const c = window.TradingViewApi?.activeChart?.();
 if (!c || c.symbol() !== symbol || String(c.resolution()) !== resolution)
   return {verified:false, reason:'Chart symbol/timeframe mismatch or API unavailable'};
 if (!c.createShape || !c.getShapeById || !c.removeEntity || !c.getVisibleRange || !c.setVisibleRange)
   return {verified:false, reason:'Native drawing readback or viewport API unavailable'};
 const ids = []; let saved;
 const verify = () => ids.every((id,i) => {
   const p = c.getShapeById(id).getPoints(); const wanted = commands[i].point;
   return p.length === 1 && p[0].time === wanted.time && Math.abs(p[0].price-wanted.price) < 1e-9;
 });
 try {
   saved = c.getVisibleRange();
   for (const cmd of commands) {
     const id = await c.createShape(cmd.point, {shape:'horizontal_line', text:cmd.label,
       lock:true, disableSelection:true, disableSave:true, overrides:{linecolor:cmd.color, linewidth:2, showLabel:true}});
     if (!id) throw Error('No drawing ID returned'); ids.push(id);
   }
   if (!verify()) throw Error('Drawing anchors differ from signal');
   const width = saved.to-saved.from;
   if (!(width>0)) throw Error('No verifiable viewport');
   await c.setVisibleRange({from:saved.from+width*.1,to:saved.to-width*.1});
   if (!verify()) throw Error('Anchors changed after zoom');
   await c.setVisibleRange({from:saved.from+width*.1,to:saved.to+width*.1});
   if (!verify()) throw Error('Anchors changed after pan');
   if (c.symbol() !== symbol || String(c.resolution()) !== resolution) throw Error('Chart changed during drawing');
   return {verified:true, ids, symbol, resolution, timeframe_change_verified:false};
 } catch(e) {
   for (const id of ids) {try {c.removeEntity(id);} catch (_) {}}
   return {verified:false, reason:String(e)};
 } finally {if(saved) {try {await c.setVisibleRange(saved);} catch (_) {}}}
}"""


def drawing_plan(signal):
    when = int(signal.created_at.timestamp())
    points = [("Entry", signal.entry, "#56d6ac"), ("Stop / invalidation", signal.stop, "#f07878")]
    points += [(f"TP {i}", p, "#79b9e8") for i, p in enumerate(signal.targets, 1)]
    commands = [
        {"point": {"time": when, "price": p}, "label": f"MSnR {signal.id[:8]} · {name}", "color": color}
        for name, p, color in points
    ]
    from datetime import datetime

    for feature in signal.chart_features:
        commands.append(
            {
                "point": {
                    "time": int(datetime.fromisoformat(feature["time"]).timestamp()),
                    "price": feature["price"],
                },
                "label": feature["label"],
                "color": "#b5a6db",
            }
        )
    return commands


class TradingView:
    """Supported visible UI interactions only; unverified canvas drawings never authorize delivery."""

    def __init__(self, profile: Path, executable: str | None = None):
        self.profile = profile
        self.executable = executable or os.getenv("MSNR_CHROME_EXECUTABLE")

    def inspect(self, destination: Path) -> dict:
        from playwright.sync_api import sync_playwright, Error

        destination.mkdir(parents=True, exist_ok=True)
        self.profile.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            kwargs = {"headless": True, "viewport": {"width": 1440, "height": 1000}}
            if self.executable:
                kwargs["executable_path"] = self.executable
            else:
                kwargs["channel"] = "chrome"
            context = p.chromium.launch_persistent_context(str(self.profile), **kwargs)
            try:
                page = context.new_page()
                response = page.goto(TARGET, wait_until="domcontentloaded", timeout=45000)
                page.screenshot(path=str(destination / "tradingview-reference.png"), full_page=True)
                title = page.title()
                login = page.get_by_role("button", name="Sign in", exact=False).count() > 0
                capability = page.evaluate(CAPABILITY)
                return {
                    "url": TARGET,
                    "title": title,
                    "http_status": response.status if response else None,
                    "login_may_be_required": login,
                    "native_drawings_verified": False,
                    "native_api": capability,
                    "reason": "Public TradingView UI exposes no verified broker price/time drawing transform in this session. Use deterministic broker chart.",
                    "reference_screenshot": str(destination / "tradingview-reference.png"),
                }
            except Error as exc:
                result = {
                    "url": TARGET,
                    "native_drawings_verified": False,
                    "status": "browser_or_network_blocked",
                    "reason": str(exc).split("Call log:")[0][:500],
                    "fallback": "Deterministic broker-data rendering remains available",
                }
                import json

                (destination / "capability.json").write_text(json.dumps(result, indent=2))
                return result
            finally:
                context.close()

    def chart(self, signal, bars, directory: Path):
        # Native screenshots are not sent as signal charts without exact feed and coordinate verification.
        return render(signal, bars, directory)

    def annotate(self, signal, expected_symbol, cdp_url="http://127.0.0.1:9222"):
        """Optional workspace visualization. Discord still uses exact broker OHLC rendering."""
        from playwright.sync_api import sync_playwright, Error

        parsed = urlsplit(cdp_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Chrome debugging endpoint must be loopback HTTP")
        resolutions = {
            "M1": "1",
            "M3": "3",
            "M5": "5",
            "M15": "15",
            "M30": "30",
            "H1": "60",
            "H4": "240",
            "D1": "1D",
            "W1": "1W",
            "MN1": "1M",
        }
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(cdp_url, timeout=10000)
                page = next(
                    (
                        page
                        for context in browser.contexts
                        for page in context.pages
                        if page.url.split("?")[0].rstrip("/") == TARGET.rstrip("/")
                    ),
                    None,
                )
                if page is None:
                    return {
                        "verified": False,
                        "reason": "Open the configured TradingView layout in the dedicated Chrome session",
                    }
                result = page.evaluate(
                    DRAW,
                    {
                        "symbol": expected_symbol,
                        "resolution": resolutions[signal.timeframe],
                        "commands": drawing_plan(signal),
                    },
                )
                result["broker_feed_verified"] = False
                result["discord_chart_source"] = "MT5 broker OHLC deterministic renderer"
                # Disconnect Playwright without closing the user's Chrome session.
                return result
        except Error as exc:
            return {"verified": False, "reason": str(exc).split("Call log:")[0][:300]}
