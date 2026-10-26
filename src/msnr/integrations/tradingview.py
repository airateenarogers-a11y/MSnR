from __future__ import annotations

import os
from pathlib import Path

from ..charts import render

TARGET = "https://www.tradingview.com/chart/O7UQR2ba/"


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
                return {
                    "url": TARGET,
                    "title": title,
                    "http_status": response.status if response else None,
                    "login_may_be_required": login,
                    "native_drawings_verified": False,
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
