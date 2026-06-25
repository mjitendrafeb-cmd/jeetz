"""
Shared utilities: folder scanning, state markers, retry decorator.
No Playwright imports here — keeps this module independently testable.
"""
from __future__ import annotations

import functools
import logging
import time
import traceback
from pathlib import Path
from typing import Callable, List, TypeVar

logger = logging.getLogger("claude_automation")

F = TypeVar("F", bound=Callable)


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(
    retries: int = 3,
    delay: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator that re-runs a function on failure with exponential back-off.

    Back-off schedule (delay=2.0): 2s → 4s → 8s …
    Works correctly on both plain functions and instance methods.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    backoff = delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"[{func.__name__}] attempt {attempt}/{retries} failed: {exc}. "
                        f"Retrying in {backoff:.1f}s…"
                    )
                    if attempt < retries:
                        time.sleep(backoff)
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator


# ---------------------------------------------------------------------------
# Folder helpers
# ---------------------------------------------------------------------------

def get_company_folders(queue_path: Path) -> List[Path]:
    """Return all subdirectories of queue_path sorted alphabetically."""
    if not queue_path.exists():
        raise FileNotFoundError(f"Queue folder not found: {queue_path}")
    return sorted(
        (p for p in queue_path.iterdir() if p.is_dir()),
        key=lambda p: p.name.lower(),
    )


def get_pdf_files(folder: Path) -> List[Path]:
    """Return all *.pdf files in folder, sorted by name."""
    return sorted(folder.glob("*.pdf"), key=lambda p: p.name.lower())


# ---------------------------------------------------------------------------
# State markers
# ---------------------------------------------------------------------------

def is_completed(folder: Path) -> bool:
    return (folder / "completed.ok").exists()


def mark_completed(folder: Path) -> None:
    (folder / "completed.ok").touch()
    logger.info(f"[{folder.name}] Marked as completed.")


def mark_failed(folder: Path, error: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    content = f"Failed at: {ts}\n\n{error}\n"
    (folder / "failed.txt").write_text(content, encoding="utf-8")
    logger.error(f"[{folder.name}] Marked as failed.")


# ---------------------------------------------------------------------------
# Screenshot helper (for debugging failures)
# ---------------------------------------------------------------------------

def save_debug_screenshot(page, folder: Path, label: str) -> None:
    """Save a screenshot to the company folder for post-mortem debugging."""
    try:
        dest = folder / f"debug_{label}_{int(time.time())}.png"
        page.screenshot(path=str(dest), full_page=True)
        logger.info(f"Debug screenshot saved: {dest.name}")
    except Exception as exc:
        logger.debug(f"Could not save debug screenshot: {exc}")
