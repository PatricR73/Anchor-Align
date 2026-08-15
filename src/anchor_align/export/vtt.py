"""S8 — VTT export, validated independently against webvtt-py."""

from __future__ import annotations

import logging
from pathlib import Path

from anchor_align.models import Cue

logger = logging.getLogger(__name__)

# Inter-cue gap floor applied at write time, and the ceiling on how large
# an overlap this writer will silently paper over. Sub-millisecond touches
# are rounding/interpolation-boundary artifacts (two segments meeting
# exactly at a shared word boundary), not real timing conflicts — a viewer
# glitches on a literal zero/negative gap, so those get nudged apart here.
# A genuine overlap is a QC-visible problem, not a formatting one:
# `export.qc.qc_report`'s OVERLAP check already flags it, and this writer
# must not clamp it away and hide it.
GAP_FLOOR_S = 0.040
MAX_CLAMPED_OVERLAP_S = 0.050


def _format_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def format_vtt(cues: list[Cue]) -> str:
    """Return `cues` as a WebVTT string (the exact bytes write_vtt writes).

    Cue numbering blocks use `cue.index` directly — WebVTT cue identifiers
    are optional free-form text per spec, so no renumbering is imposed here;
    whatever index S5 assigned is what a QC message referencing `cue_index`
    will match against in the file.

    A cue whose `start` precedes the previous cue's `end` by less than
    MAX_CLAMPED_OVERLAP_S is nudged to `prev_end + GAP_FLOOR_S` for display
    purposes only — a writer-level formatting fix for sub-millisecond
    boundary touches, not an alignment correction, and it does not mutate
    the `Cue` objects passed in (qc_report must still see the original,
    unclamped timings). A larger overlap is left untouched and stays
    visible in the output.
    """
    lines = ["WEBVTT", ""]
    prev_end: float | None = None
    for cue in cues:
        start = cue.start
        if prev_end is not None and start < prev_end and prev_end - start < MAX_CLAMPED_OVERLAP_S:
            start = prev_end + GAP_FLOOR_S
        lines.append(str(cue.index))
        lines.append(f"{_format_timestamp(start)} --> {_format_timestamp(cue.end)}")
        lines.extend(cue.lines)
        lines.append("")
        prev_end = cue.end
    return "\n".join(lines)


def write_vtt(cues: list[Cue], output_path: Path) -> Path:
    """Write `cues` as a WebVTT file (see format_vtt for the formatting)."""
    output_path.write_text(format_vtt(cues), encoding="utf-8")
    logger.info("wrote %d cues to %s", len(cues), output_path)
    return output_path
