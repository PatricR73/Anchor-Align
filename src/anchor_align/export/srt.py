"""S8 — SRT export (bonus format alongside VTT)."""

from __future__ import annotations

import logging
from pathlib import Path

from anchor_align.models import Cue

logger = logging.getLogger(__name__)


def _format_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_srt(cues: list[Cue]) -> str:
    """Return `cues` as an SRT string (the exact bytes write_srt writes).

    Unlike WebVTT, SRT's sequence numbers are not optional decoration — most
    parsers expect a contiguous 1-based sequence. `cue.index` is used as-is
    (not remapped): the caller (S5) is responsible for handing this function
    cues already numbered 1..N in order, the same assumption write_vtt makes
    when it uses `cue.index` for cross-referencing QC messages.
    """
    blocks = []
    for cue in cues:
        block = "\n".join(
            [
                str(cue.index),
                f"{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}",
                *cue.lines,
            ]
        )
        blocks.append(block)
    return "\n\n".join(blocks) + "\n"


def write_srt(cues: list[Cue], output_path: Path) -> Path:
    """Write `cues` as an SRT file (see format_srt for the formatting)."""
    output_path.write_text(format_srt(cues), encoding="utf-8")
    logger.info("wrote %d cues to %s", len(cues), output_path)
    return output_path
