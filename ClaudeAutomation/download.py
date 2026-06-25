"""
Download management: waits for the HTML artifact's Download button to appear
then captures the download and saves it to a caller-specified path.

Playwright's expect_download() context manager intercepts the browser-level
download event, so the file is captured regardless of where the browser's
own download folder is configured.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeoutError

from browser import SELECTORS, find_element, find_element_optional

logger = logging.getLogger("claude_automation")


class DownloadManager:
    """Handles artifact download from Claude's artifact panel."""

    def __init__(self, page: Page, download_timeout: int, retry_count: int = 3) -> None:
        self._page = page
        self._timeout = download_timeout      # ms
        self._retries = retry_count

    def wait_and_download(self, target_path: Path) -> None:
        """
        Find the Download button in the Claude artifact panel, click it,
        intercept the resulting file download, and save it to target_path.

        Retries up to self._retries times with exponential back-off.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                self._do_download(target_path)
                return
            except Exception as exc:
                last_exc = exc
                backoff = 2.0 * (2 ** (attempt - 1))
                logger.warning(
                    f"[download] Attempt {attempt}/{self._retries} failed: {exc}. "
                    f"Retrying in {backoff:.0f}s…"
                )
                if attempt < self._retries:
                    time.sleep(backoff)

        raise RuntimeError(
            f"Download failed after {self._retries} attempts: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_download(self, target_path: Path) -> None:
        logger.info("Waiting for HTML artifact Download button…")

        download_btn = find_element(
            self._page,
            SELECTORS["download_button"],
            timeout=self._timeout,
        )

        logger.info("Download button found — initiating download…")

        with self._page.expect_download(timeout=self._timeout) as dl_info:
            download_btn.click()

        dl = dl_info.value

        if dl.failure():
            raise RuntimeError(f"Browser reported download failure: {dl.failure()}")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        dl.save_as(str(target_path))

        if not target_path.exists() or target_path.stat().st_size == 0:
            raise RuntimeError(
                f"Download appeared to succeed but file is missing or empty: {target_path}"
            )

        logger.info(
            f"HTML artifact saved: {target_path.name} "
            f"({target_path.stat().st_size:,} bytes)"
        )
