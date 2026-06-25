"""
Structured logging: timestamped output to both file and stdout.
Call setup_logger() once at startup; every module uses
logging.getLogger("claude_automation") after that.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOGGER_NAME = "claude_automation"


def setup_logger(log_file: Path, level: int = logging.INFO) -> logging.Logger:
    """
    Configure the application logger.  Safe to call multiple times —
    handlers are only added once.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger(_LOGGER_NAME)
    if log.handlers:
        return log  # already initialised

    log.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    fh.setFormatter(fmt)
    log.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)

    return log


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
