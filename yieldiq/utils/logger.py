# utils/logger.py
# ─────────────────────────────────────────────────────────────
# Lightweight logging setup used by every module.
# Call get_logger(__name__) at the top of each file.
# ─────────────────────────────────────────────────────────────

import logging
import sys


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a named logger with a consistent format."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        # Use reconfigure() on Python 3.7+ to force UTF-8 on Windows terminals
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s  %(levelname)-8s  %(name)s  |  %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger
