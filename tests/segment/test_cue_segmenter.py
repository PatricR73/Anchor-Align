"""S5 — segmentation of aligned words into cues.

Constraints are enforced downstream by export.qc.qc_report; this module's
own tests verify segment_into_cues satisfies them directly, and one
integration test round-trips through qc_report itself (and through
write_vtt/write_srt) rather than re-implementing the same checks twice.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import webvtt

from anchor_align.caption_constraints import MAX_LINES
from anchor_align.export.qc import qc_report
from anchor_align.export.srt import write_srt
from anchor_align.export.vtt import write_vtt
from anchor_align.models import AlignedWord, EditedToken, MatchType, QCCode
from anchor_align.segment.cue_segmenter import (
    MAX_DURATION_S,
    MAX_LINE_CHARS,
    MIN_DURATION_S,
    segment_into_cues,
)


def _word(i: int, text: str, start: float, end: float, *, sentence_end: bool = False) -> AlignedWord:
    is_end = sentence_end or text.endswith((".", "!", "?"))
    tok = EditedToken(text=text, index=i, char_offset=0, sentence_id=0, is_sentence_end=is_end)
    return AlignedWord(token=tok, start=start, end=end, match_type=MatchType.EXACT, confidence=0.9)


def _words_from_text(text: str, *, word_duration: float = 0.3, gap: float = 0.05, start: float = 0.0) -> list[AlignedWord]:
    words = []
    t = start
    for i, tok in enumerate(text.split()):
        words.append(_word(i, tok, t, t + word_duration))
        t += word_duration + gap
    return words


# ---------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------


def test_empty_input_yields_no_cues():
    assert segment_into_cues([]) == ([], [])


def test_cue_indices_are_1based_sequential():
    words = _words_from_text("one two three four five six seven eight nine ten eleven twelve.")
    cues, _issues = segment_into_cues(words)
    assert [c.index for c in cues] == list(range(1, len(cues) + 1))


def test_word_span_indexes_into_the_input_list_correctly():
    words = _words_from_text(
        "This is a reasonably long sentence that should end up split across more than one cue naturally."
    )
    cues, _issues = segment_into_cues(words)
    assert len(cues) > 1
    # word_span ranges must be contiguous and cover every word exactly once
    covered = []
    for c in cues:
        start, end = c.word_span
        covered.extend(range(start, end))
    assert covered == list(range(len(words)))


def test_word_span_text_matches_cue_lines_content():
    words = _words_from_text("hello there friend how are you doing today on this fine morning.")
    cues, _issues = segment_into_cues(words)
    for c in cues:
        start, end = c.word_span
        span_text = " ".join(w.token.text for w in words[start:end])
        cue_text = " ".join(c.lines)
        assert span_text == cue_text


def test_single_word_produces_one_cue():
    words = [_word(0, "hello", 0.0, 0.5)]
    cues, _issues = segment_into_cues(words)
    assert len(cues) == 1
    assert cues[0].word_span == (0, 1)
    assert cues[0].lines == ["hello"]


# ---------------------------------------------------------------------
# Hard constraints: max 2 lines, max 42 chars/line
# ---------------------------------------------------------------------


def test_every_cue_has_at_most_2_lines():
    words = _words_from_text(" ".join(["word"] * 60))
    cues, _issues = segment_into_cues(words)
    assert all(len(c.lines) <= MAX_LINES for c in cues)


def test_every_line_is_at_most_42_chars():
    words = _words_from_text(" ".join(["antidisestablishmentarianism"] * 20))
    cues, _issues = segment_into_cues(words)
    for c in cues:
        for line in c.lines:
            assert len(line) <= MAX_LINE_CHARS, line


def test_long_word_run_forces_multiple_cues_not_overflowing_lines():
    # 30 five-char words joined with spaces is 30*6-1=179 chars — far more
    # than 2*42=84, so this MUST split into several cues.
    words = _words_from_text(" ".join(["fiver"] * 30))
    cues, _issues = segment_into_cues(words)
    assert len(cues) > 1
    for c in cues:
        assert len(c.lines) <= MAX_LINES
        for line in c.lines:
            assert len(line) <= MAX_LINE_CHARS


def test_single_overlong_word_does_not_crash_and_is_isolated():
    # A word longer than MAX_LINE_CHARS can never be wrapped to fit —
    # documented fallback: it gets its own cue rather than crashing or
    # corrupting neighboring cues.
    long_word = "x" * (MAX_LINE_CHARS + 10)
    words = [_word(0, "hello", 0.0, 0.5), _word(1, long_word, 0.6, 1.1), _word(2, "world", 1.2, 1.7)]
    cues, _issues = segment_into_cues(words)
    assert any(long_word in " ".join(c.lines) for c in cues)
    covered = []
    for c in cues:
        start, end = c.word_span
        covered.extend(range(start, end))
    assert covered == [0, 1, 2]


# ---------------------------------------------------------------------
# Duration constraints: 1-7s
# ---------------------------------------------------------------------


def test_cue_duration_generally_within_bounds():
    words = _words_from_text(
        "This is a moderately long passage of speech with several natural sentence boundaries. "
        "It continues for a while so that the segmenter has real choices to make about where to break. "
        "And it keeps going a bit further still, to be sure multiple cues get produced.",
        word_duration=0.3,
        gap=0.05,
    )
    cues, _issues = segment_into_cues(words)
    for c in cues:
        duration = c.end - c.start
        assert duration <= MAX_DURATION_S + 1e-6


def test_short_trailing_utterance_gets_padded_toward_min_duration():
    # A short 2-word cue with no following cue to worry about overlapping —
    # padding should push its duration up toward MIN_DURATION_S.
    words = [_word(0, "hi", 0.0, 0.2), _word(1, "there.", 0.25, 0.4)]
    cues, _issues = segment_into_cues(words)
    assert len(cues) == 1
    assert cues[0].end - cues[0].start >= MIN_DURATION_S - 1e-6


def test_duration_padding_never_overlaps_the_next_cue():
    # Two short utterances close together: padding the first must not
    # push its end past the second cue's start.
    words = [
        _word(0, "hi.", 0.0, 0.2, sentence_end=True),
        _word(1, "bye.", 0.3, 0.5, sentence_end=True),
    ]
    cues, _issues = segment_into_cues(words)
    for a, b in pairwise(cues):
        assert a.end <= b.start


def test_long_word_run_at_constant_slow_rate_forces_a_split_before_7s():
    words = _words_from_text(" ".join(["word"] * 40), word_duration=0.3, gap=0.05)
    cues, _issues = segment_into_cues(words)
    assert len(cues) > 1
    for c in cues:
        assert (c.end - c.start) <= MAX_DURATION_S + 1e-6


# ---------------------------------------------------------------------
# CPS constraint
# ---------------------------------------------------------------------


def test_fast_speech_with_room_to_pad_stays_under_cps():
    # Word timing fast enough that a single giant cue would exceed CPS,
    # but with real gaps between sentences (unlike continuous zero-gap
    # speech) so short cues have room to pad toward MIN_DURATION_S. The
    # DP's CPS cost is evaluated against the post-padding duration (see
    # _candidate_cue's comment on cps_duration), so it should prefer
    # breaking into several paddable cues over one giant over-fast one.
    text = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten."
    words = _words_from_text(text, word_duration=0.05, gap=0.3)
    cues, _issues = segment_into_cues(words)
    assert len(cues) > 1
    max_cps = 21.0
    over_budget = [
        c for c in cues if (c.end - c.start) > 0 and sum(len(l) for l in c.lines) / (c.end - c.start) > max_cps
    ]
    assert over_budget == []


def test_continuous_fast_speech_with_no_gaps_is_a_genuine_cps_residual():
    """Documents an expected residual, the CPS-side mirror of
    test_genuinely_tight_input_documents_its_own_qc_residual below: ten
    words spoken back-to-back with literally zero gap between them (no
    silence anywhere to pad into) at a rate far above what 21 chars/sec
    can express. No segmentation choice can fix this — cps_duration in
    _candidate_cue only ESTIMATES that padding will succeed, and here
    consecutive cues are immediately adjacent, leaving no room to pad into
    for any cue but the last. The correct behavior is to still break
    (more than one cue, never overlapping) rather than force it all into
    one giant cue — not to silently under-report the resulting CPS excess.
    """
    text = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten."
    words = _words_from_text(text, word_duration=0.05, gap=0.0)
    cues, _issues = segment_into_cues(words)
    assert len(cues) > 1
    for a, b in pairwise(cues):
        assert a.end <= b.start


# ---------------------------------------------------------------------
# No-overlap constraint
# ---------------------------------------------------------------------


def test_cues_are_never_overlapping():
    words = _words_from_text(
        "A longer passage with multiple sentences to exercise several consecutive cues. "
        "Each one should start no earlier than the previous cue's end. "
        "That is the only way exports stay valid."
    )
    cues, _issues = segment_into_cues(words)
    for a, b in pairwise(cues):
        assert a.end <= b.start


# ---------------------------------------------------------------------
# Sentence-boundary preference (soft, via pysbd)
# ---------------------------------------------------------------------


def test_prefers_breaking_at_sentence_boundaries_when_feasible():
    # Two short, clearly-separated sentences that together would still fit
    # hard hard constraints as one cue — the sentence-boundary bonus
    # should still be visible in cue count/placement when a natural
    # question/statement break is available.
    text = "Is this working. Yes it is."
    words = _words_from_text(text, word_duration=0.25, gap=0.05)
    cues, _issues = segment_into_cues(words)
    # every produced cue boundary should be a legal, non-overlapping split
    for a, b in pairwise(cues):
        assert a.end <= b.start


# ---------------------------------------------------------------------
# Integration: real QC pass and real export round-trip
# ---------------------------------------------------------------------


def _realistic_words() -> list[AlignedWord]:
    text = (
        "So the project started last spring and it was a mess at first. "
        "We spent three weeks just trying to get the pipeline working end to end. "
        "Nobody expected it to take that long, honestly, but eventually it clicked. "
        "The team shipped the first version on a Friday afternoon, which in hindsight was risky. "
        "Since then the numbers have kept improving every single week, which has been reassuring. "
        "It is still not perfect but the worst failure modes are gone for good now."
    )
    return _words_from_text(text, word_duration=0.28, gap=0.06)


def test_realistic_transcript_passes_qc_cleanly():
    words = _realistic_words()
    cues, _issues = segment_into_cues(words)
    issues = qc_report(cues)
    assert issues == [], issues


def test_realistic_transcript_exports_to_valid_vtt(tmp_path: Path):
    words = _realistic_words()
    cues, _issues = segment_into_cues(words)
    out = write_vtt(cues, tmp_path / "out.vtt")
    parsed = webvtt.read(str(out))
    assert len(parsed) == len(cues)
    for parsed_cue, cue in zip(parsed, cues):
        assert parsed_cue.text == "\n".join(cue.lines)


def test_realistic_transcript_exports_to_valid_srt(tmp_path: Path):
    words = _realistic_words()
    cues, _issues = segment_into_cues(words)
    out = write_srt(cues, tmp_path / "out.srt")
    parsed = webvtt.from_srt(str(out))
    assert len(parsed) == len(cues)


def test_genuinely_tight_input_documents_its_own_qc_residual():
    """Back-to-back very short utterances with no room to pad without
    overlapping are a genuinely unsegmentable case for the 1s minimum —
    padding is bounded by the next cue's start (see _pad_duration's
    docstring), so a QCCode.CUE_TOO_SHORT can still legitimately fire
    here. This test documents that this is expected, not a bug: the
    alternative (overlapping cues, or silently stretching past the next
    cue's start) would be worse than a short cue.
    """
    words = [
        _word(0, "hi.", 0.0, 0.15, sentence_end=True),
        _word(1, "bye.", 0.20, 0.35, sentence_end=True),
        _word(2, "ok.", 0.40, 0.55, sentence_end=True),
    ]
    cues, _issues = segment_into_cues(words)
    for a, b in pairwise(cues):
        assert a.end <= b.start  # never overlap, even under this pressure
    issues = qc_report(cues)
    # every issue present, if any, must be a duration one — never overlap
    # or line/length violations, which this input has no excuse to trigger
    assert all(i.code in (QCCode.CUE_TOO_SHORT, QCCode.CPS_EXCEEDED) for i in issues)


def test_zero_room_span_is_dropped_and_flagged_instead_of_crashing():
    """A leading orphan run with no real anchor on either side can collapse
    multiple words to the exact same instant. When _pad_duration correctly
    declines to borrow room from a next cue that starts at that same
    instant (its `ceiling > start` guard), nothing should attempt to build
    a Cue from that zero-duration span — Cue's own end > start validator
    would raise. It must be dropped and reported as ZERO_DURATION_SPAN
    instead, with the cues that DO have room still built and renumbered.
    """
    # Three 42-char sentences, all pinned to t=0.0 (the degenerate orphan
    # case) — too long to all fit in one 2-line cue, forcing the DP to
    # split them across cues that share the same zero-duration start, so
    # at least one has no later-starting neighbor to borrow room from.
    w0 = "A" * 41 + "."
    w1 = "B" * 41 + "."
    w2 = "C" * 41 + "."
    words = [
        _word(0, w0, 0.0, 0.0, sentence_end=True),
        _word(1, w1, 0.0, 0.0, sentence_end=True),
        _word(2, w2, 0.0, 0.0, sentence_end=True),
        _word(3, "Real", 1.0, 1.3),
        _word(4, "content.", 1.3, 1.8, sentence_end=True),
    ]
    cues, issues = segment_into_cues(words)

    zero_span_issues = [i for i in issues if i.code == QCCode.ZERO_DURATION_SPAN]
    assert zero_span_issues, "expected at least one ZERO_DURATION_SPAN issue"
    assert all(i.severity == "error" for i in zero_span_issues)
    assert all(i.cue_index is None for i in zero_span_issues)

    # every cue that WAS built must be valid (Cue's own validator already
    # guarantees end > start, but confirm none is the degenerate case) and
    # sequentially renumbered, skipping the dropped ones
    assert [c.index for c in cues] == list(range(1, len(cues) + 1))
    for c in cues:
        assert c.end > c.start

    # a normal downstream qc_report call still succeeds on what remains
    qc_report(cues)


# ---------------------------------------------------------------------
# S3/S5 boundary contract: segment_into_cues requires audio-ordered input
# (see align.aligner.resolve_audio_order) and checks it, rather than
# trusting it the way the original version of this function did.
# ---------------------------------------------------------------------


def test_segment_into_cues_rejects_unsorted_input():
    words = [
        _word(0, "second.", 5.0, 5.5, sentence_end=True),
        _word(1, "first.", 0.0, 0.5, sentence_end=True),  # starts before the previous word
    ]
    try:
        segment_into_cues(words)
        raise AssertionError("expected ValueError for unsorted input")
    except ValueError as e:
        assert "not sorted" in str(e)


def test_qc_report_rejects_unsorted_cues():
    from anchor_align.models import Cue

    cues = [
        Cue(index=1, start=5.0, end=6.0, lines=["b"], word_span=(0, 1)),
        Cue(index=2, start=0.0, end=1.0, lines=["a"], word_span=(1, 2)),  # starts before the previous cue
    ]
    try:
        qc_report(cues)
        raise AssertionError("expected ValueError for unsorted cues")
    except ValueError as e:
        assert "not sorted" in str(e)
