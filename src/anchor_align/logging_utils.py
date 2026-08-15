"""Logging setup for entry points (CLI, demo).

Library modules only create loggers and never configure handlers, so
embedding the package in another app leaves logging alone. Entry points
call :func:`configure_logging` once.
"""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a single console handler to the root logger, idempotently."""
    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
