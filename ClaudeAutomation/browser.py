"""
Browser lifecycle management.

Uses Playwright's persistent context to load an existing Chrome profile
so the automation inherits an already-authenticated Claude session.
Chrome must be fully closed before launching — they cannot share a profile.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)

from config import Config

logger = logging.getLogger("claude_automation")

# ---------------------------------------------------------------------------
# Ordered fallback selector lists for every Claude UI element we interact with.
# If Claude updates its DOM, add the new selector at the TOP of the relevant list.
# ---------------------------------------------------------------------------
SELECTORS: dict[str, list[str]] = {
    "new_chat": [
        # aria-label variations
        "button[aria-label='New chat']",
        "a[aria-label='New chat']",
        # data-testid variations
        "[data-testid='new-chat-button']",
        "[data-testid='new-chat-link']",
        # text-content fallbacks
        "button:has-text('New chat')",
        "a:has-text('New chat')",
        # broad fallback
        "[aria-label*='new chat' i]",
    ],
    "upload_trigger": [
        "button[aria-label='Add attachments']",
        "button[aria-label*='Attach' i]",
        "button[aria-label*='Upload' i]",
        "[data-testid='attachment-button']",
        "[data-testid='file-upload-button']",
        "button[aria-label*='file' i]",
        "label[aria-label*='attach' i]",
    ],
    "file_input": [
        "input[type='file']",
        "input[accept*='pdf']",
        "input[accept*='.pdf']",
    ],
    "chat_input": [
        # Most specific first
        "div[contenteditable='true'][data-testid='chat-input']",
        "div[contenteditable='true'][aria-label*='message' i]",
        "div[contenteditable='true'].ProseMirror",
        "div[contenteditable='true']",
        "textarea[placeholder*='message' i]",
        "textarea[data-testid='chat-textarea']",
    ],
    "send_button": [
        "button[aria-label='Send message']",
        "button[data-testid='send-button']",
        "button[aria-label*='Send' i]",
        "button[type='submit']",
    ],
    "stop_button": [
        "button[aria-label='Stop generating']",
        "button[aria-label*='Stop' i]",
        "[data-testid='stop-button']",
        "button:has-text('Stop')",
    ],
    "download_button": [
        # Artifact panel download — most specific first
        "[data-testid='artifact-download-button']",
        "button[aria-label='Download']",
        "button[aria-label*='Download' i]",
        "button[aria-label*='Save' i]",
        "button:has-text('Download')",
        "a[download]",
    ],
    "attachment_chips": [
        # Indicators that files have been staged for upload
        "[data-testid='attachment-chip']",
        "[data-testid='file-preview']",
        "[data-testid='file-chip']",
        ".attachment-chip",
        ".file-chip",
        "[aria-label*='attachment' i]",
        "figure[aria-label*='.pdf' i]",
    ],
}

# Chrome launch flags that reduce automation-detection friction
_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]


def find_element(page: Page, selectors: list[str], timeout: int = 10_000):
    """
    Try each selector in order; return the first visible element found.
    Raises RuntimeError if none match within `timeout` milliseconds each.
    """
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                return el
        except PWTimeoutError:
            continue
    raise RuntimeError(
        f"Element not found. Tried {len(selectors)} selectors:\n  " +
        "\n  ".join(selectors)
    )


def find_element_optional(
    page: Page, selectors: list[str], timeout: int = 3_000
) -> Optional[object]:
    """Same as find_element but returns None instead of raising."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                return el
        except PWTimeoutError:
            continue
    return None


class BrowserManager:
    """
    Context-manager wrapper around a Playwright persistent Chrome context.

    Usage::

        with BrowserManager(config) as browser:
            page = browser.new_page()
            ...
    """

    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._pw: Optional[Playwright] = None
        self._ctx: Optional[BrowserContext] = None

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "BrowserManager":
        self.launch()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def launch(self) -> None:
        logger.info(
            f"Launching Chrome — profile: {self._cfg.chrome_profile_path} "
            f"[{self._cfg.chrome_profile_name}]"
        )

        self._pw = sync_playwright().start()

        args = _CHROME_ARGS + [
            f"--profile-directory={self._cfg.chrome_profile_name}",
        ]

        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self._cfg.chrome_profile_path),
            channel="chrome",           # use the system-installed Chrome binary
            headless=self._cfg.headless,
            slow_mo=self._cfg.slow_mo,
            args=args,
            accept_downloads=True,
        )
        self._ctx.set_default_timeout(self._cfg.navigation_timeout)
        logger.info("Browser launched successfully.")

    def close(self) -> None:
        if self._ctx:
            try:
                self._ctx.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        logger.info("Browser closed.")

    # ------------------------------------------------------------------
    # Page management
    # ------------------------------------------------------------------

    def new_page(self) -> Page:
        if not self._ctx:
            raise RuntimeError("BrowserManager not launched. Call launch() or use as context manager.")
        page = self._ctx.new_page()
        page.set_default_timeout(self._cfg.navigation_timeout)
        return page

    def close_page(self, page: Page) -> None:
        try:
            page.close()
        except Exception:
            pass
