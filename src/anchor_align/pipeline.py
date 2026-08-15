"""End-to-end wiring of the S3-S8 stages.

One function (`align_to_cues`) that runs align -> resolve_audio_order ->
segment_into_cues -> qc_report in the mandated order and returns the
result together with every QC finding. The demo and the CLI both call this
instead of re-wiring the stages themselves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from anchor_align.align.aligner import align, resolve_audio_order
from anchor_align.export.qc import qc_report
from anchor_align.interfaces import PhoneticEncoder
from anchor_align.models import AlignedWord, Cue, EditedToken, QCIssue, STTWord
from anchor_align.segment.cue_segmenter import segment_into_cues

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Output of one align_to_cues call.

    `aligned` is in edited/document order; `audio_order` is the same words
    sorted by true timestamp — the only list safe to hand to
    segment_into_cues or the export writers. `issues` aggregates the
    TRANSPOSED_BLOCK findings from resolve_audio_order, the
    ZERO_DURATION_SPAN findings from segmentation, and the QC report.
    """

    aligned: list[AlignedWord]
    audio_order: list[AlignedWord]
    cues: list[Cue]
    issues: list[QCIssue]

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


def align_to_cues(
    stt_words: list[STTWord],
    edited_tokens: list[EditedToken],
    *,
    phonetic_encoder: PhoneticEncoder | None = None,
) -> PipelineResult:
    """Run the full S3-S8 chain over STT words and an edited transcript.

    Returns the aligned words (edited order), the audio-ordered words, the
    segmented cues, and every QC finding. Raises ValueError if the inputs
    violate a stage contract (the same checks each stage performs on its
    own); downstream consumers must use `audio_order`, never `aligned`.

    `phonetic_encoder` is passed through to `align`; `None` keeps the
    aligner's default (phonetic matching off by measurement).
    """
    aligned = align(stt_words, edited_tokens, phonetic_encoder=phonetic_encoder)
    audio_order, order_issues = resolve_audio_order(aligned)
    cues, segment_issues = segment_into_cues(audio_order)
    export_issues = qc_report(cues)
    issues = [*order_issues, *segment_issues, *export_issues]

    logger.info(
        "pipeline: %d words -> %d cues, %d error(s), %d warning(s)",
        len(audio_order),
        len(cues),
        sum(1 for i in issues if i.severity == "error"),
        sum(1 for i in issues if i.severity == "warning"),
    )
    return PipelineResult(
        aligned=aligned,
        audio_order=audio_order,
        cues=cues,
        issues=issues,
    )
