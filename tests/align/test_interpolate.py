"""S3c — interpolation for unmatched edited words."""

from __future__ import annotations

from anchor_align.align.interpolate import interpolate_gaps
from anchor_align.models import AlignedWord, EditedToken, MatchType


def _et(i: int, text: str) -> EditedToken:
    return EditedToken(text=text, index=i, char_offset=0, sentence_id=0, is_sentence_end=False)


def _matched(i: int, text: str, start: float, end: float) -> AlignedWord:
    return AlignedWord(token=_et(i, text), start=start, end=end, match_type=MatchType.ANCHOR, confidence=1.0)


def _gap(i: int, text: str) -> AlignedWord:
    return AlignedWord(token=_et(i, text), start=0.0, end=0.0, match_type=MatchType.INTERPOLATED, confidence=0.0)


def test_no_gaps_leaves_words_untouched():
    words = [_matched(0, "a", 0.0, 1.0), _matched(1, "b", 1.0, 2.0)]
    assert interpolate_gaps(words) == words


def test_single_word_gap_fills_the_whole_span():
    words = [_matched(0, "a", 0.0, 1.0), _gap(1, "bb"), _matched(2, "c", 3.0, 4.0)]
    out = interpolate_gaps(words)
    assert out[1].start == 1.0
    assert out[1].end == 3.0
    assert out[1].match_type == MatchType.INTERPOLATED  # unchanged, per contract


def test_multi_word_gap_splits_proportionally_by_syllables():
    # "a" ~ 1 syllable, "beautiful" ~ 4 syllables -> roughly 1:4 split of the 5s gap
    words = [_matched(0, "x", 0.0, 0.0), _gap(1, "a"), _gap(2, "beautiful"), _matched(3, "y", 5.0, 5.0)]
    out = interpolate_gaps(words)
    first_span = out[1].end - out[1].start
    second_span = out[2].end - out[2].start
    assert first_span < second_span
    assert out[1].start == 0.0
    assert out[2].end == 5.0
    assert out[1].end == out[2].start  # contiguous, no overlap or hole


def test_gap_at_start_of_stream_pins_to_the_first_timed_neighbor():
    words = [_gap(0, "hi"), _matched(1, "a", 2.0, 3.0)]
    out = interpolate_gaps(words)
    assert out[0].start == 2.0
    assert out[0].end == 2.0


def test_gap_at_end_of_stream_pins_to_the_last_timed_neighbor():
    words = [_matched(0, "a", 0.0, 1.0), _gap(1, "hi")]
    out = interpolate_gaps(words)
    assert out[1].start == 1.0
    assert out[1].end == 1.0


def test_all_gaps_no_timed_neighbors_at_all():
    words = [_gap(0, "a"), _gap(1, "b")]
    out = interpolate_gaps(words)
    assert all(w.start == 0.0 and w.end == 0.0 for w in out)


def test_matched_words_are_never_modified():
    matched = _matched(0, "a", 0.0, 1.0)
    words = [matched, _gap(1, "b"), _matched(2, "c", 3.0, 4.0)]
    out = interpolate_gaps(words)
    assert out[0] == matched
    assert out[2] == words[2]
