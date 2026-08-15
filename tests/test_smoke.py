"""S0 smoke test: every module must import cleanly, plus the contract tests
that back the "done when" criteria — cheap tests that catch a broken
contract immediately instead of three modules downstream."""

import importlib

import pytest
from pydantic import ValidationError

from anchor_align.caption_constraints import (
    MAX_CPS,
    MAX_DURATION_S,
    MAX_LINE_CHARS,
    MAX_LINES,
    MIN_DURATION_S,
)
from anchor_align.models import (
    AlignedWord,
    AlignmentMetrics,
    Cue,
    EditedToken,
    MatchType,
    NormalizedToken,
    QCCode,
    QCIssue,
    STTWord,
)
from anchor_align.segment.cue_segmenter import MAX_CPS as SEG_MAX_CPS
from anchor_align.segment.cue_segmenter import MAX_DURATION_S as SEG_MAX_DURATION_S
from anchor_align.segment.cue_segmenter import MAX_LINE_CHARS as SEG_MAX_LINE_CHARS
from anchor_align.segment.cue_segmenter import MIN_DURATION_S as SEG_MIN_DURATION_S

MODULES = [
    "anchor_align.models",
    "anchor_align.interfaces",
    "anchor_align.exceptions",
    "anchor_align.logging_utils",
    "anchor_align.caption_constraints",
    "anchor_align.contractions",
    "anchor_align.corrupt.corruptor",
    "anchor_align.corrupt.corpus",
    "anchor_align.normalize.normalizer",
    "anchor_align.align.anchors",
    "anchor_align.align.needleman_wunsch",
    "anchor_align.align.interpolate",
    "anchor_align.align.aligner",
    "anchor_align.benchmark.adapters",
    "anchor_align.benchmark.baseline",
    "anchor_align.benchmark.runner",
    "anchor_align.benchmark.drift",
    "anchor_align.benchmark.plots",
    "anchor_align.segment.cue_segmenter",
    "anchor_align.ingest.audio",
    "anchor_align.ingest.document",
    "anchor_align.stt.faster_whisper_adapter",
    "anchor_align.stt.whisperx_adapter",
    "anchor_align.stt.elevenlabs_adapter",
    "anchor_align.stt.cache",
    "anchor_align.export.vtt",
    "anchor_align.export.srt",
    "anchor_align.export.qc",
    "anchor_align.pipeline",
    "anchor_align.cli",
]


def test_all_modules_import():
    for name in MODULES:
        importlib.import_module(name)


def _edited_token() -> EditedToken:
    return EditedToken(text="hi", index=0, char_offset=0, sentence_id=0, is_sentence_end=True)


def test_inverted_span_raises():
    with pytest.raises(ValidationError):
        STTWord(text="hi", start=2.0, end=1.0)


def test_zero_duration_word_is_legal():
    STTWord(text="hi", start=1.0, end=1.0)


def test_zero_duration_cue_raises():
    with pytest.raises(ValidationError):
        Cue(index=0, start=1.0, end=1.0, lines=["hi"], word_span=(0, 1))


def test_quantization_can_collapse_a_short_real_span_to_zero_duration():
    # 0.3ms apart, but both round to the same 1ms grid point — this is the
    # exact failure mode CueBuilder must guard against before construction.
    assert round(1.0001, 3) == round(1.0004, 3)
    with pytest.raises(ValidationError):
        Cue(index=0, start=1.0001, end=1.0004, lines=["hi"], word_span=(0, 1))


def test_quantization_idempotent():
    # A value already on the 1ms grid must survive re-validation unchanged,
    # and dump -> load -> dump must be byte-identical. Golden files depend
    # on this; it's the property that silently breaks if round() is ever
    # swapped for a Decimal path.
    word = STTWord(text="hi", start=0.001, end=0.002)
    dumped_once = word.model_dump_json()
    reloaded = STTWord.model_validate_json(dumped_once)
    assert reloaded == word
    assert reloaded.model_dump_json() == dumped_once


def test_alignment_metrics_rejects_zero_words():
    with pytest.raises(ValidationError):
        AlignmentMetrics(
            mean_abs_boundary_error_ms=10.0,
            mean_signed_boundary_error_ms=-2.0,
            p95_abs_boundary_error_ms=20.0,
            measured_word_count=1,
            match_type_counts={},
        )


def test_alignment_metrics_rejects_measured_count_exceeding_word_count():
    with pytest.raises(ValidationError):
        AlignmentMetrics(
            mean_abs_boundary_error_ms=10.0,
            mean_signed_boundary_error_ms=-2.0,
            p95_abs_boundary_error_ms=20.0,
            measured_word_count=5,
            match_type_counts={MatchType.ANCHOR: 2, MatchType.INTERPOLATED: 1},
        )


def test_alignment_metrics_distribution_is_derived_from_counts():
    # Three counts whose ratios don't sum to exactly 1.0 in binary float —
    # this is exactly why counts are stored instead of the distribution.
    metrics = AlignmentMetrics(
        mean_abs_boundary_error_ms=10.0,
        mean_signed_boundary_error_ms=-2.0,
        p95_abs_boundary_error_ms=20.0,
        measured_word_count=2,
        match_type_counts={MatchType.ANCHOR: 1, MatchType.EXACT: 1, MatchType.INTERPOLATED: 1},
    )
    assert metrics.word_count == 3
    assert metrics.measured_word_count == 2  # interpolated word excluded from the error sample
    dist = metrics.match_type_distribution
    assert dist[MatchType.ANCHOR] == pytest.approx(1 / 3)
    assert sum(dist.values()) == pytest.approx(1.0)


def test_match_type_serializes_as_value_not_name():
    aligned = AlignedWord(
        token=_edited_token(), start=0.0, end=1.0, match_type=MatchType.PHONETIC, confidence=0.5
    )
    assert aligned.model_dump()["match_type"] == "phonetic"
    assert '"phonetic"' in aligned.model_dump_json()


def test_confidence_out_of_range_raises():
    with pytest.raises(ValidationError):
        STTWord(text="hi", start=0.0, end=1.0, confidence=1.5)
    with pytest.raises(ValidationError):
        AlignedWord(
            token=_edited_token(),
            start=0.0,
            end=1.0,
            match_type=MatchType.EXACT,
            confidence=-0.1,
        )


@pytest.mark.parametrize(
    "instance",
    [
        STTWord(text="hi", start=0.0, end=1.0, confidence=0.9, speaker="A"),
        _edited_token(),
        NormalizedToken(surface="Hi", normal="hi", char_span=(0, 2), keys=("H",), source_indices=(0,)),
        AlignedWord(
            token=_edited_token(),
            start=0.0,
            end=1.0,
            match_type=MatchType.ANCHOR,
            confidence=1.0,
        ),
        Cue(index=0, start=0.0, end=1.0, lines=["hi"], word_span=(0, 1)),
        QCIssue(severity="warning", code=QCCode.CPS_EXCEEDED, message="too fast", cue_index=0),
        AlignmentMetrics(
            mean_abs_boundary_error_ms=12.5,
            mean_signed_boundary_error_ms=-3.2,
            p95_abs_boundary_error_ms=40.0,
            measured_word_count=9,
            match_type_counts={MatchType.ANCHOR: 6, MatchType.EXACT: 3, MatchType.INTERPOLATED: 1},
        ),
    ],
)
def test_json_roundtrip(instance):
    cls = type(instance)
    assert cls.model_validate_json(instance.model_dump_json()) == instance


def test_segmentation_and_qc_share_one_constraint_source():
    """The limits segmentation enforces and the limits QC reports against
    must come from the same module — if they drift, QC can flag what the
    segmenter already guarantees (or worse, miss what it doesn't)."""
    assert MAX_LINES == 2
    assert MAX_LINE_CHARS == SEG_MAX_LINE_CHARS == 42
    assert MIN_DURATION_S == SEG_MIN_DURATION_S == 1.0
    assert MAX_DURATION_S == SEG_MAX_DURATION_S == 7.0
    assert MAX_CPS == SEG_MAX_CPS == 21.0
