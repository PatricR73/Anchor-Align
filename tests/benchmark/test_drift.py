"""S4 — compute_drift: does boundary error grow toward the end of a
document? Unit tests against synthetic AlignedWord/STTWord/TokenMapping
data — deterministic scenarios, not corpus-scale runs (see
tests/benchmark/test_long_file_drift_benchmark.py for those).
"""

from __future__ import annotations

import pytest

from anchor_align.benchmark.drift import compute_drift, document_has_reorder
from anchor_align.models import AlignedWord, EditedToken, MatchType, STTWord, TokenMapping


def _gold(i: int, start: float, end: float) -> STTWord:
    return STTWord(text=f"w{i}", start=start, end=end)


def _edited(i: int) -> EditedToken:
    return EditedToken(text=f"w{i}", index=i, char_offset=0, sentence_id=0, is_sentence_end=False)


def _pred(i: int, start: float, end: float, match_type: MatchType = MatchType.EXACT) -> AlignedWord:
    return AlignedWord(token=_edited(i), start=start, end=end, match_type=match_type, confidence=0.9)


def _mapping(i: int, gold_index: int | None) -> TokenMapping:
    return TokenMapping(edited_index=i, gold_indices=() if gold_index is None else (gold_index,))


def _uniform_100_words(error_ms: float = 0.0):
    """100 gold words, 1s apart; predictions offset by a constant error at
    every position (or exact, if error_ms=0)."""
    gold = [_gold(i, float(i), float(i) + 0.5) for i in range(100)]
    predicted = [_pred(i, float(i) + error_ms / 1000, float(i) + 0.5 + error_ms / 1000) for i in range(100)]
    mapping = tuple(_mapping(i, i) for i in range(100))
    return predicted, gold, mapping


def test_no_error_gives_zero_drift_in_both_buckets():
    predicted, gold, mapping = _uniform_100_words(error_ms=0.0)
    result = compute_drift(predicted, gold, mapping)
    assert result.body_mean_abs_error_ms == 0.0
    assert result.tail_mean_abs_error_ms == 0.0
    assert result.tail_minus_body_mean_abs_error_ms == 0.0


def test_uniform_error_gives_near_zero_delta():
    """A constant offset everywhere is NOT drift — body and tail should
    score the same, since the failure mode isn't growing over time."""
    predicted, gold, mapping = _uniform_100_words(error_ms=50.0)
    result = compute_drift(predicted, gold, mapping)
    assert result.body_mean_abs_error_ms == pytest.approx(50.0, abs=1.0)
    assert result.tail_mean_abs_error_ms == pytest.approx(50.0, abs=1.0)
    assert result.tail_minus_body_mean_abs_error_ms == pytest.approx(0.0, abs=1.0)


def test_growing_error_produces_positive_delta():
    """Error that grows linearly toward the end — the cumulative-drift
    signature — must show up as a clearly positive
    tail_minus_body_mean_abs_error_ms."""
    gold = [_gold(i, float(i), float(i) + 0.5) for i in range(100)]
    predicted = [_pred(i, float(i) + i * 0.01, float(i) + 0.5 + i * 0.01) for i in range(100)]  # error grows with i
    mapping = tuple(_mapping(i, i) for i in range(100))

    result = compute_drift(predicted, gold, mapping)
    assert result.tail_mean_abs_error_ms > result.body_mean_abs_error_ms
    assert result.tail_minus_body_mean_abs_error_ms > 0


def test_split_is_by_timeline_not_token_count():
    """100 gold words spaced 1s apart except the last 10, which are
    packed into the final second — the tail (final 10% of the 100s
    timeline) should contain far more than the last-10%-of-tokens if the
    split were done by token index instead."""
    gold = [_gold(i, float(i), float(i) + 0.5) for i in range(90)]
    gold += [_gold(90 + i, 90.0 + i * 0.1, 90.0 + i * 0.1 + 0.05) for i in range(10)]
    predicted = [_pred(i, gold[i].start, gold[i].end) for i in range(100)]
    mapping = tuple(_mapping(i, i) for i in range(100))

    result = compute_drift(predicted, gold, mapping)
    # timeline-based split: tail = last 10% of a 91s document = words with
    # true_start >= 81.9s, i.e. words 82-99 (18 words) — not just the
    # packed final 10 by token count.
    assert result.tail_measured_count > 10


def test_interpolated_predictions_are_excluded():
    predicted, gold, mapping = _uniform_100_words()
    predicted[50] = _pred(50, 0.0, 0.0, match_type=MatchType.INTERPOLATED)
    result = compute_drift(predicted, gold, mapping)
    assert result.body_measured_count + result.tail_measured_count == 99


def test_inserted_tokens_with_no_gold_source_are_excluded():
    predicted, gold, mapping = _uniform_100_words()
    mapping = list(mapping)
    mapping[50] = _mapping(50, None)
    result = compute_drift(predicted, gold, tuple(mapping))
    assert result.body_measured_count + result.tail_measured_count == 99


def test_mismatched_lengths_raise():
    predicted, gold, mapping = _uniform_100_words()
    with pytest.raises(ValueError, match="1:1"):
        compute_drift(predicted, gold, mapping[:-1])


def test_empty_stt_words_raises():
    predicted, _gold, mapping = _uniform_100_words()
    with pytest.raises(ValueError, match="no timeline"):
        compute_drift(predicted, [], mapping)


def test_invalid_tail_fraction_raises():
    predicted, gold, mapping = _uniform_100_words()
    with pytest.raises(ValueError, match="tail_fraction"):
        compute_drift(predicted, gold, mapping, tail_fraction=0.0)
    with pytest.raises(ValueError, match="tail_fraction"):
        compute_drift(predicted, gold, mapping, tail_fraction=1.5)


def test_no_scorable_words_in_tail_raises():
    """Every word interpolated in the final 10% of the timeline — nothing
    to report for the tail bucket."""
    gold = [_gold(i, float(i), float(i) + 0.5) for i in range(100)]
    predicted = [_pred(i, float(i), float(i) + 0.5) for i in range(100)]
    for i in range(89, 100):  # total_duration=99.5, cutoff=89.55 -> word 89 (start=89.0) is the last body word
        predicted[i] = _pred(i, 0.0, 0.0, match_type=MatchType.INTERPOLATED)
    mapping = tuple(_mapping(i, i) for i in range(100))
    with pytest.raises(ValueError, match="tail"):
        compute_drift(predicted, gold, mapping)


def test_custom_tail_fraction():
    gold = [_gold(i, float(i), float(i) + 0.5) for i in range(100)]
    predicted = [_pred(i, float(i), float(i) + 0.5) for i in range(100)]
    mapping = tuple(_mapping(i, i) for i in range(100))
    result = compute_drift(predicted, gold, mapping, tail_fraction=0.5)
    assert result.body_measured_count + result.tail_measured_count == 100
    assert result.tail_measured_count > 30  # roughly half, loosely


def test_max_is_at_least_mean():
    predicted, gold, mapping = _uniform_100_words(error_ms=10.0)
    result = compute_drift(predicted, gold, mapping)
    assert result.body_max_abs_error_ms >= result.body_mean_abs_error_ms
    assert result.tail_max_abs_error_ms >= result.tail_mean_abs_error_ms


# --------------------------------------------------------------------------
# document_has_reorder
# --------------------------------------------------------------------------


def test_document_has_reorder_true_when_effective_rate_nonzero():
    effective_config = (("filler_removal", 0.03), ("sentence_reorder", 0.68))
    assert document_has_reorder(effective_config) is True


def test_document_has_reorder_false_when_effective_rate_zero():
    effective_config = (("filler_removal", 0.03), ("sentence_reorder", 0.0))
    assert document_has_reorder(effective_config) is False


def test_document_has_reorder_false_when_absent_entirely():
    effective_config = (("filler_removal", 0.03),)
    assert document_has_reorder(effective_config) is False
