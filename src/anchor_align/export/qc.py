"""S8 — QC report: verifies every S5 constraint against the produced cues
and JSON confidence output, sorting files worst-scored to best.
"""

from __future__ import annotations

import json
import logging
import statistics
from itertools import pairwise
from pathlib import Path

from anchor_align.caption_constraints import (
    MAX_CPS,
    MAX_DURATION_S,
    MAX_LINE_CHARS,
    MAX_LINES,
    MIN_DURATION_S,
)
from anchor_align.models import AlignedWord, Cue, QCCode, QCIssue

logger = logging.getLogger(__name__)


def qc_report(cues: list[Cue]) -> list[QCIssue]:
    """Check every cue against the caption constraints (max 2 lines, max
    42 chars/line, 1-7s duration, max 21 chars/s, no overlaps with the
    previous cue). `cues` must be sorted by `start` — the same order
    `segment_into_cues` produces — since overlap is only meaningful checked
    against the immediately preceding cue in presentation order. Checked
    below, not assumed: unsorted input would make the overlap check
    silently meaningless rather than raise.
    """
    for a, b in pairwise(cues):
        if b.start < a.start:
            raise ValueError(
                f"cues is not sorted by start ({b.start} < {a.start}) — qc_report's OVERLAP check "
                "is only meaningful on cues in presentation order"
            )

    issues: list[QCIssue] = []
    prev_end: float | None = None
    for cue in cues:
        if len(cue.lines) > MAX_LINES:
            issues.append(
                QCIssue(
                    severity="error",
                    code=QCCode.TOO_MANY_LINES,
                    message=f"{len(cue.lines)} lines (max {MAX_LINES})",
                    cue_index=cue.index,
                )
            )

        for line in cue.lines:
            if len(line) > MAX_LINE_CHARS:
                issues.append(
                    QCIssue(
                        severity="warning",
                        code=QCCode.LINE_TOO_LONG,
                        message=f"line is {len(line)} chars (max {MAX_LINE_CHARS}): {line!r}",
                        cue_index=cue.index,
                    )
                )

        duration = cue.duration
        if duration < MIN_DURATION_S:
            issues.append(
                QCIssue(
                    severity="warning",
                    code=QCCode.CUE_TOO_SHORT,
                    message=f"duration {duration:.3f}s < minimum {MIN_DURATION_S}s",
                    cue_index=cue.index,
                )
            )
        if duration > MAX_DURATION_S:
            issues.append(
                QCIssue(
                    severity="warning",
                    code=QCCode.CUE_TOO_LONG,
                    message=f"duration {duration:.3f}s > maximum {MAX_DURATION_S}s",
                    cue_index=cue.index,
                )
            )

        char_count = sum(len(line) for line in cue.lines)
        cps = char_count / duration if duration > 0 else float("inf")
        if cps > MAX_CPS:
            issues.append(
                QCIssue(
                    severity="warning",
                    code=QCCode.CPS_EXCEEDED,
                    message=f"{cps:.1f} chars/sec (max {MAX_CPS})",
                    cue_index=cue.index,
                )
            )

        if prev_end is not None and cue.start < prev_end:
            issues.append(
                QCIssue(
                    severity="error",
                    code=QCCode.OVERLAP,
                    message=f"starts at {cue.start}s, before the previous cue ends at {prev_end}s",
                    cue_index=cue.index,
                )
            )
        prev_end = cue.end

    if issues:
        logger.warning("qc found %d issues across %d cues", len(issues), len(cues))
    return issues


def format_confidence_json(cues: list[Cue], aligned_words: list[AlignedWord]) -> str:
    """Return per-cue confidence stats as a JSON string: mean/min confidence
    over the `AlignedWord`s each cue's `word_span` covers — the same
    AlignedWord list CueBuilder was called with, per `Cue.word_span`'s
    contract. Confidence lives on `AlignedWord`, not `Cue`, so
    `aligned_words` is required here rather than derived from `cues` alone.
    """
    report = []
    for cue in cues:
        start, end = cue.word_span
        span_words = aligned_words[start:end]
        confidences = [w.confidence for w in span_words]
        report.append(
            {
                "cue_index": cue.index,
                "start": cue.start,
                "end": cue.end,
                "mean_confidence": statistics.mean(confidences) if confidences else None,
                "min_confidence": min(confidences) if confidences else None,
                "word_count": len(span_words),
            }
        )
    return json.dumps(report, indent=2)


def write_confidence_json(cues: list[Cue], aligned_words: list[AlignedWord], output_path: Path) -> Path:
    """Write per-cue confidence stats as JSON (see format_confidence_json)."""
    output_path.write_text(format_confidence_json(cues, aligned_words), encoding="utf-8")
    return output_path
