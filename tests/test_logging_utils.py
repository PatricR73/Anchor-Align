"""Logging setup: entry points configure once, library modules stay
silent by default."""

from __future__ import annotations

import logging

from anchor_align.logging_utils import configure_logging


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    before = len(root.handlers)
    configure_logging(logging.INFO)
    configure_logging(logging.INFO)
    assert len(root.handlers) == max(before, 1)


def test_configure_logging_sets_level():
    configure_logging(logging.DEBUG)
    assert logging.getLogger().level == logging.DEBUG
