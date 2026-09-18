"""Test data and formatting utilities."""

from __future__ import annotations

import logging
from typing import Optional


def get_logger(name: str) -> logging.Logger:
    """Get a pre-configured logger that sanitizes PII."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def format_ms(ms: Optional[float]) -> str:
    """Format milliseconds into a readable string."""
    if ms is None:
        return "N/A"
    if ms < 1.0:
        return f"{ms:.2f} ms"
    elif ms < 1000.0:
        return f"{ms:.1f} ms"
    else:
        return f"{ms/1000.0:.2f} s"
