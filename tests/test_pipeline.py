"""Pipeline integration: align_to_cues runs the whole chain end to end —
align, audio-order resolution, segmentation, QC — and the pieces agree
with each other the way the stage contracts promise.
"""

from __future__ import annotations

from itertools import pairwise

from anchor_align.models import Cue, EditedToken, MatchType, QCCode, STTWord
from anchor_align.pipeline import align_to_cues


def _stt_words(texts: list[str], *, gap: float = 0.1, duration: float = 0.4) -> list[STTWord]:
    out = []
    t = 0.0
    for w in texts:
        out.append(STTWord(text=w, start=t, end=t + duration))
        t += duration + gap
    return out


def _edited_tokens(texts: list[str]) -> list[EditedToken]:
    return [
        EditedToken(text=w, index=i, char_offset=0, sentence_id=0, is_sentence_end=w.endswith((".", "!", "?")))
        for i, w in enumerate(texts)
    ]


def test_clean_document_yields_cues_without_issues():
    words = [
        "Hello", "world.", "This", "is", "a", "short", "test", "of", "the", "pipeline.",
    ]
    result = align_to_cues(_stt_words(words), _edited_tokens(words))
    assert result.cues
    assert result.issues == []
    for a, b in pairwise(result.cues):
        assert a.end <= b.start


def test_audio_order_is_sorted_by_true_timestamp():
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot."]
    result = align_to_cues(_stt_words(words), _edited_tokens(words))
    starts = [w.start for w in result.audio_order]
    assert starts == sorted(starts)


def test_issues_aggregate_across_stages():
    # A reordered document must surface TRANSPOSED_BLOCK from
    # resolve_audio_order through the pipeline's aggregated issue list.
    gold = ["there", "was", "no", "fanfare", "at", "all", ".", "Siobhan", "was", "the", "one", "who", "finally", "found", "the", "bug", "in", "the", "ingestion", "layer", ".", "nobody", "expected", "the", "migration", "to", "go", "this", "smoothly", "given", "how", "old", "the", "system", "was", "."]
    edited = ["there", "was", "no", "fanfare", "at", "all", ".", "nobody", "expected", "the", "migration", "to", "go", "this", "smoothly", "given", "how", "old", "the", "system", "was", ".", "Siobhan", "was", "the", "one", "who", "finally", "found", "the", "bug", "in", "the", "ingestion", "layer", "."]
    result = align_to_cues(_stt_words(gold, gap=0.05, duration=0.3), _edited_tokens(edited))
    assert any(i.code == QCCode.TRANSPOSED_BLOCK for i in result.issues)
    assert result.error_count == 0  # transposition is info, not an error


def test_word_span_ranges_cover_every_word_exactly_once():
    words = [
        "This", "sentence", "is", "long", "enough", "that", "the", "segmenter",
        "must", "produce", "more", "than", "one", "cue", "to", "satisfy",
        "the", "duration", "constraints", "on", "the", "timeline.",
    ]
    result = align_to_cues(_stt_words(words, gap=0.25, duration=0.3), _edited_tokens(words))
    covered: list[int] = []
    for cue in result.cues:
        start, end = cue.word_span
        covered.extend(range(start, end))
    assert covered == list(range(len(words)))
    assert all(isinstance(c, Cue) for c in result.cues)
    assert all(c.end > c.start for c in result.cues)


def test_empty_input_yields_empty_pipeline_result():
    result = align_to_cues([], [])
    assert result.cues == []
    assert result.issues == []
    assert result.aligned == []


def test_match_type_breakdown_includes_anchors():
    words = ["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog."]
    result = align_to_cues(_stt_words(words), _edited_tokens(words))
    types = {w.match_type for w in result.aligned}
    assert types <= {MatchType.ANCHOR, MatchType.EXACT}
