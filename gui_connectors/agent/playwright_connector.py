"""Playwright GUI connector for the mock legacy bank portal.

DOM-first navigation (stable selectors). Screenshot capture is optional for
Set-of-Mark / vision demos without replacing the primary automation path.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data_plane.config import DOWNLOAD_DIR, ensure_dirs


@dataclass
class GuiRunResult:
    status: str
    portal_url: str
    downloaded_file: str | None
    steps: list[str]
    screenshot_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def download_bank_statement(
    *,
    portal_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    headless: bool = True,
    capture_screenshot: bool = True,
) -> dict[str, Any]:
    """Login → Statements → download CSV via Playwright."""
    from playwright.sync_api import sync_playwright

    ensure_dirs()
    portal_url = portal_url or os.getenv("LEGACY_PORTAL_URL", "http://127.0.0.1:8765/")
    username = username or os.getenv("LEGACY_PORTAL_USER", "analyst")
    password = password or os.getenv("LEGACY_PORTAL_PASS", "demo123")
    steps: list[str] = []
    screenshot_path = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            page.goto(portal_url, wait_until="domcontentloaded")
            steps.append("open_login")

            page.get_by_test_id("username").fill(username)
            page.get_by_test_id("password").fill(password)
            page.get_by_test_id("login-btn").click()
            page.get_by_text("Welcome, Analyst").wait_for(timeout=5000)
            steps.append("login_ok")

            page.get_by_test_id("nav-statements").click()
            page.get_by_test_id("download-csv").wait_for(timeout=5000)
            steps.append("open_statements")

            if capture_screenshot:
                shot = DOWNLOAD_DIR / "portal_statements.png"
                page.screenshot(path=str(shot), full_page=True)
                screenshot_path = str(shot)
                steps.append("screenshot_statements")

            with page.expect_download() as download_info:
                page.get_by_test_id("download-csv").click()
            download = download_info.value
            target = DOWNLOAD_DIR / download.suggested_filename
            download.save_as(str(target))
            steps.append(f"downloaded:{target.name}")

            result = GuiRunResult(
                status="success",
                portal_url=portal_url,
                downloaded_file=str(target),
                steps=steps,
                screenshot_path=screenshot_path,
            )
            return result.to_dict()
        except Exception as exc:  # noqa: BLE001
            fail_shot = DOWNLOAD_DIR / "portal_failure.png"
            try:
                page.screenshot(path=str(fail_shot), full_page=True)
                screenshot_path = str(fail_shot)
            except Exception:
                pass
            return GuiRunResult(
                status="error",
                portal_url=portal_url,
                downloaded_file=None,
                steps=steps,
                screenshot_path=screenshot_path,
                error=str(exc),
            ).to_dict()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    import json

    print(json.dumps(download_bank_statement(), indent=2))
