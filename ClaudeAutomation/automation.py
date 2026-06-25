"""
Claude PR Audit Automation — main entry point and workflow orchestrator.

Run with:
    python automation.py                  # uses config.json in current directory
    python automation.py /path/config.json
"""
from __future__ import annotations

import logging
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeoutError

from browser import BrowserManager, SELECTORS, find_element, find_element_optional
from config import Config
from download import DownloadManager
from helpers import (
    get_company_folders,
    get_pdf_files,
    is_completed,
    mark_completed,
    mark_failed,
    retry,
    save_debug_screenshot,
)
from logger import setup_logger

logger = logging.getLogger("claude_automation")


class ClaudeWorkflow:
    """
    Executes the full PR Audit workflow for a single company folder:

        navigate → new chat → upload PDFs → invoke skill →
        send → wait for completion → download HTML artifact
    """

    def __init__(self, config: Config, page: Page) -> None:
        self._cfg = config
        self._page = page
        self._downloader = DownloadManager(
            page=page,
            download_timeout=config.download_timeout,
            retry_count=config.retry_count,
        )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self, folder: Path) -> None:
        """Process one company folder end-to-end."""
        logger.info(f"{'─' * 62}")
        logger.info(f"Starting  : {folder.name}")

        pdf_files = get_pdf_files(folder)
        if not pdf_files:
            raise ValueError(f"No PDF files found in {folder}.")
        logger.info(f"Found {len(pdf_files)} PDF(s): {[p.name for p in pdf_files]}")

        self._navigate_to_project()
        self._open_new_chat()
        self._upload_pdfs(pdf_files)
        self._invoke_skill()
        self._send_message()
        self._wait_for_response()
        self._downloader.wait_and_download(folder / "PR Audit Report.html")

    # ------------------------------------------------------------------
    # Step 1 — Navigate
    # ------------------------------------------------------------------

    def _navigate_to_project(self) -> None:
        logger.info(f"Navigating to project URL…")
        self._page.goto(
            self._cfg.project_url,
            wait_until="domcontentloaded",
            timeout=self._cfg.navigation_timeout,
        )
        self._page.wait_for_load_state("networkidle", timeout=self._cfg.navigation_timeout)

    # ------------------------------------------------------------------
    # Step 2 — New Chat
    # ------------------------------------------------------------------

    def _open_new_chat(self) -> None:
        logger.info("Opening new chat…")
        btn = find_element(
            self._page,
            SELECTORS["new_chat"],
            timeout=self._cfg.navigation_timeout,
        )
        btn.click()
        # Wait for the chat input to be ready before proceeding
        self._page.wait_for_load_state("networkidle", timeout=self._cfg.navigation_timeout)
        find_element(
            self._page,
            SELECTORS["chat_input"],
            timeout=self._cfg.navigation_timeout,
        )
        logger.info("New chat ready.")

    # ------------------------------------------------------------------
    # Step 3 — Upload PDFs
    # ------------------------------------------------------------------

    @retry(retries=3, delay=2.0)
    def _upload_pdfs(self, pdf_files: list[Path]) -> None:
        logger.info(f"Uploading {len(pdf_files)} PDF(s)…")
        str_paths = [str(p) for p in pdf_files]

        # Strategy A: set files directly on the hidden <input type="file">
        file_input = find_element_optional(
            self._page, SELECTORS["file_input"], timeout=3_000
        )
        if file_input:
            file_input.set_input_files(str_paths)
        else:
            # Strategy B: click the attach button → file-chooser dialog
            upload_btn = find_element(
                self._page,
                SELECTORS["upload_trigger"],
                timeout=self._cfg.navigation_timeout,
            )
            with self._page.expect_file_chooser(
                timeout=self._cfg.upload_timeout
            ) as fc_info:
                upload_btn.click()
            fc_info.value.set_files(str_paths)

        self._wait_for_uploads_complete(expected=len(pdf_files))
        logger.info("All PDFs uploaded.")

    def _wait_for_uploads_complete(self, expected: int) -> None:
        """
        Poll until attachment preview chips equal `expected`, or the send
        button becomes enabled — whichever comes first.
        Falls back to a short fixed wait if neither indicator is found.
        """
        logger.info("Waiting for uploads to complete…")
        deadline = time.monotonic() + self._cfg.upload_timeout / 1_000

        while time.monotonic() < deadline:
            # Check for attachment chips
            for sel in SELECTORS["attachment_chips"]:
                chips = self._page.query_selector_all(sel)
                if len(chips) >= expected:
                    logger.info(f"Detected {len(chips)} attachment chip(s).")
                    return

            # Check if send button is already enabled (all uploads done)
            send_btn = find_element_optional(
                self._page, SELECTORS["send_button"], timeout=1_000
            )
            if send_btn and send_btn.is_enabled():
                logger.info("Send button enabled — uploads complete.")
                return

            time.sleep(0.5)

        logger.warning(
            "Upload wait timed out — attachment chips not detected. "
            "Proceeding; uploads may still be in progress."
        )

    # ------------------------------------------------------------------
    # Step 4 — Invoke skill
    # ------------------------------------------------------------------

    @retry(retries=3, delay=2.0)
    def _invoke_skill(self) -> None:
        """
        Type the slash command into the chat input and select the matching
        skill from the autocomplete dropdown that Claude displays.
        """
        logger.info(f"Invoking skill: {self._cfg.skill_name}")
        chat_input = find_element(
            self._page,
            SELECTORS["chat_input"],
            timeout=self._cfg.navigation_timeout,
        )
        chat_input.click()

        # Type character-by-character so Claude's autocomplete can react
        for char in self._cfg.skill_name:
            self._page.keyboard.type(char)
            time.sleep(0.08)  # brief pause per character — not a fixed total wait

        # Build selectors targeting the skill label in the dropdown
        lbl = self._cfg.skill_label  # e.g. "pr-audit-master"
        skill_selectors = [
            f"[role='option']:has-text('{lbl}')",
            f"[role='menuitem']:has-text('{lbl}')",
            f"[role='listitem']:has-text('{lbl}')",
            f"[data-testid='command-item']:has-text('{lbl}')",
            f"li:has-text('{lbl}')",
            f"button:has-text('{lbl}')",
        ]

        skill_item = find_element_optional(
            self._page, skill_selectors, timeout=8_000
        )

        if skill_item:
            logger.info("Skill dropdown item found — clicking…")
            skill_item.click()
        else:
            # The full text was typed; press Enter to accept the first suggestion
            logger.warning(
                "Skill dropdown not matched by selector — pressing Enter to accept."
            )
            self._page.keyboard.press("Enter")

        logger.info("Skill selected.")

    # ------------------------------------------------------------------
    # Step 5 — Send
    # ------------------------------------------------------------------

    def _send_message(self) -> None:
        logger.info("Sending message…")
        send_btn = find_element(
            self._page,
            SELECTORS["send_button"],
            timeout=self._cfg.navigation_timeout,
        )

        # Wait up to 30 s for the button to become enabled
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if send_btn.is_enabled():
                break
            time.sleep(0.3)
        else:
            raise RuntimeError("Send button never became enabled within 30 s.")

        send_btn.click()
        logger.info("Message sent — waiting for Claude to respond…")

    # ------------------------------------------------------------------
    # Step 6 — Wait for response
    # ------------------------------------------------------------------

    def _wait_for_response(self) -> None:
        """
        Three-phase wait:
          Phase 1 — stop button appears   → Claude has started generating
          Phase 2 — stop button disappears → Claude finished
          Phase 3 — send button re-enables (fallback if stop button not found)
        """
        timeout_ms = self._cfg.response_timeout

        # Phase 1: wait for generation to start (up to 15 s)
        stop_appeared = False
        for sel in SELECTORS["stop_button"]:
            try:
                self._page.wait_for_selector(sel, timeout=15_000, state="visible")
                stop_appeared = True
                logger.info("Claude is generating (stop button visible)…")
                break
            except PWTimeoutError:
                continue

        if not stop_appeared:
            logger.warning(
                "Stop button did not appear — Claude may have responded instantly "
                "or is using an updated UI."
            )

        # Phase 2: wait for stop button to disappear → generation complete
        for sel in SELECTORS["stop_button"]:
            try:
                self._page.wait_for_selector(sel, timeout=timeout_ms, state="hidden")
                logger.info("Stop button hidden — Claude finished generating.")
                # Small grace period for the artifact panel to fully render
                time.sleep(1.5)
                return
            except PWTimeoutError:
                continue

        # Phase 3: fallback — poll send button enabled state
        logger.info(
            "Stop button selector not matched; polling send button state (fallback)…"
        )
        deadline = time.monotonic() + timeout_ms / 1_000
        while time.monotonic() < deadline:
            btn = find_element_optional(self._page, SELECTORS["send_button"], timeout=2_000)
            if btn and btn.is_enabled():
                logger.info("Send button re-enabled — Claude finished generating.")
                time.sleep(1.5)
                return
            time.sleep(1.0)

        raise RuntimeError(
            f"Claude did not finish generating within "
            f"{timeout_ms / 1_000:.0f}s. "
            "Increase response_timeout in config.json if the skill takes longer."
        )


# ---------------------------------------------------------------------------
# Session-level runner
# ---------------------------------------------------------------------------

class AutomationSession:
    """
    Iterates over every un-processed company folder in the queue and
    calls ClaudeWorkflow.run() for each one.

    On failure of any single folder: logs the error, writes failed.txt,
    saves a debug screenshot, and continues with the next folder.
    """

    def __init__(self, config: Config) -> None:
        self._cfg = config

    def run_all(self) -> None:
        folders = get_company_folders(self._cfg.queue_path)

        to_process = [f for f in folders if not is_completed(f)]
        already_done = len(folders) - len(to_process)

        logger.info(
            f"Queue: {len(folders)} folder(s) total | "
            f"{already_done} already done | "
            f"{len(to_process)} to process"
        )

        if not to_process:
            logger.info("All folders already processed. Nothing to do.")
            return

        with BrowserManager(self._cfg) as browser:
            for folder in to_process:
                page = browser.new_page()
                try:
                    workflow = ClaudeWorkflow(self._cfg, page)
                    workflow.run(folder)
                    mark_completed(folder)
                    logger.info(f"Completed: {folder.name}")
                except Exception:
                    tb = traceback.format_exc()
                    mark_failed(folder, tb)
                    save_debug_screenshot(page, folder, "failure")
                    logger.error(f"FAILED: {folder.name}\n{tb}")
                finally:
                    browser.close_page(page)

                logger.info(f"Moving to next folder…")

        logger.info("=" * 62)
        logger.info("All folders processed.")
        logger.info("=" * 62)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.json")

    try:
        cfg = Config.from_file(config_path)
        cfg.validate()
    except (FileNotFoundError, ValueError) as exc:
        # Can't use the file logger yet — print directly
        print(f"\n[ERROR] {exc}\n")
        sys.exit(1)

    log = setup_logger(cfg.log_file)
    log.info("=" * 62)
    log.info("Claude PR Audit Automation — Starting")
    log.info(f"Config     : {config_path.resolve()}")
    log.info(f"Queue      : {cfg.queue_path}")
    log.info(f"Project URL: {cfg.project_url}")
    log.info("=" * 62)

    try:
        session = AutomationSession(cfg)
        session.run_all()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except Exception:
        log.critical(f"Unrecoverable error:\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
