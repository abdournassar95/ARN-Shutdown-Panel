"""
Centralized application logging with rotating file output.
Replaces bare print() calls so diagnostics survive in --noconsole builds.
"""

import logging
import logging.handlers
import pathlib
import sys
from typing import Optional

from core.settings import get_settings_path

_LOGGER_NAME = "ShutdownPanel"
_logger: Optional[logging.Logger] = None


def get_log_dir() -> pathlib.Path:
    """Log directory lives next to the settings file."""
    return get_settings_path().parent / "logs"


def setup_logger(level: int = logging.INFO) -> logging.Logger:
    """Initializes and returns the application-wide logger."""
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(threadName)-18s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler: 2 MB x 3 backups (keeps disk usage bounded)
    try:
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass  # file logging is best-effort; console still works

    # Console handler (visible when running from a terminal; absent in --noconsole)
    if sys.stdout is not None:
        try:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(fmt)
            logger.addHandler(ch)
        except Exception:
            pass

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Returns the configured logger (initializing lazily if needed)."""
    return _logger if _logger is not None else setup_logger()
