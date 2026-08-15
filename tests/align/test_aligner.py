"""S3 orchestrator — align(): composes S3a -> S3b -> S3c over a full
STTWord/EditedToken stream.

test_numeral_edited_token_spans_both_matched_gold_words and
test_contraction_edited_token_spans_both_matched_gold_words are the
risk-reducing tests flagged in review: before S2's contractions/numerals
steps existed, the 1:N source_indices/variants path was completely
untested anywhere in this repo, because every S2 transform was 1:1. This
is that path, exercised end to end through S3, not just S2 in isolation.
"""

from __future__ import annotations

from itertools import pairwise

from anchor_align.align.aligner import align, resolve_audio_order
from anchor_align.models import EditedToken, MatchType, QCCode, STTWord


def _stt(words: list[str], *, gap: float = 0.2, duration: float = 0.8) -> list[STTWord]:
    out = []
    t = 0.0
    for w in words:
        out.append(STTWord(text=w, start=t, end=t + duration))
        t += duration + gap
    return out


def _edited(words: list[str]) -> list[EditedToken]:
    return [
        EditedToken(text=w, index=i, char_offset=0, sentence_id=0, is_sentence_end=False)
        for i, w in enumerate(words)
    ]


def test_identical_streams_align_exactly():
    words = ["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"]
    gold = _stt(words)
    edited = _edited(words)
    result = align(gold, edited)

    assert len(result) == len(edited)
    for aligned, gold_word in zip(result, gold):
        assert aligned.start == gold_word.start
        assert aligned.end == gold_word.end
        assert aligned.match_type in (MatchType.ANCHOR, MatchType.EXACT)
        assert aligned.confidence > 0.9


def test_output_length_always_matches_edited_token_count():
    gold = _stt(["a", "b", "c", "d", "e"])
    edited = _edited(["a", "x", "y", "d", "e"])
    result = align(gold, edited)
    assert len(result) == len(edited)


def test_output_order_matches_edited_token_order():
    gold = _stt(["alpha", "bravo", "charlie", "delta"])
    edited = _edited(["alpha", "bravo", "charlie", "delta"])
    result = align(gold, edited)
    assert [w.token.text for w in result] == ["alpha", "bravo", "charlie", "delta"]


def test_deleted_gold_word_does_not_appear_in_output():
    gold = _stt(["the", "quick", "brown", "fox"])
    edited = _edited(["the", "brown", "fox"])
    result = align(gold, edited)
    assert len(result) == 3
    assert "quick" not in [w.token.text for w in result]


def test_inserted_edited_word_gets_interpolated_timing():
    gold = _stt(["the", "brown", "fox"])
    edited = _edited(["the", "very", "brown", "fox"])
    result = align(gold, edited)
    inserted = next(w for w in result if w.token.text == "very")
    assert inserted.match_type == MatchType.INTERPOLATED
    assert inserted.start <= inserted.end
    # timing must fall between "the" and "brown" — the surrounding matches
    the_word = next(w for w in result if w.token.text == "the")
    brown_word = next(w for w in result if w.token.text == "brown")
    assert the_word.end <= inserted.start
    assert inserted.end <= brown_word.start


def test_empty_edited_tokens_yields_empty_output():
    gold = _stt(["hello", "world"])
    assert align(gold, []) == []


def test_speaker_carried_over_from_matched_stt_word():
    gold = [STTWord(text="hello", start=0.0, end=1.0, speaker="SPEAKER_1")]
    edited = _edited(["hello"])
    result = align(gold, edited)
    assert result[0].speaker == "SPEAKER_1"


# --------------------------------------------------------------------------
# The risk-reducing tests: 1:N multi-token collapse-back through S3
# --------------------------------------------------------------------------


def test_numeral_edited_token_spans_both_matched_gold_words():
    """'20%' (one edited token) must get start from the FIRST matched
    normalized token ('twenty') and end from the LAST ('percent') — the
    exact property flagged as untested before S2's numeral step existed."""
    gold_words = ["the", "rate", "was", "twenty", "percent", "higher", "than", "expected"]
    gold = _stt(gold_words)
    edited = _edited(["the", "rate", "was", "20%", "higher", "than", "expected"])

    result = align(gold, edited)

    numeral_word = next(w for w in result if w.token.text == "20%")
    twenty_word = gold[gold_words.index("twenty")]
    percent_word = gold[gold_words.index("percent")]
    assert numeral_word.start == twenty_word.start
    assert numeral_word.end == percent_word.end
    assert numeral_word.match_type == MatchType.EXACT


def test_contraction_edited_token_spans_both_matched_gold_words():
    """"don't" (one edited token) must get start from "do" and end from
    "not" — the contraction-direction mirror of the numeral case above."""
    gold_words = ["I", "do", "not", "think", "so"]
    gold = _stt(gold_words)
    edited = _edited(["I", "don't", "think", "so"])

    result = align(gold, edited)

    contraction_word = next(w for w in result if w.token.text == "don't")
    do_word = gold[gold_words.index("do")]
    not_word = gold[gold_words.index("not")]
    assert contraction_word.start == do_word.start
    assert contraction_word.end == not_word.end
    assert contraction_word.match_type == MatchType.EXACT


def test_numeral_expansion_does_not_duplicate_or_drop_neighboring_words():
    """The words immediately before/after the merged span must still
    appear exactly once in the output, correctly timed — a buggy merge
    that over-consumes adjacent deletions would silently eat a real word."""
    gold_words = ["about", "twenty", "percent", "of", "requests", "failed"]
    gold = _stt(gold_words)
    edited = _edited(["about", "20%", "of", "requests", "failed"])

    result = align(gold, edited)

    assert [w.token.text for w in result] == ["about", "20%", "of", "requests", "failed"]
    of_word = next(w for w in result if w.token.text == "of")
    assert of_word.start == gold[gold_words.index("of")].start
    assert of_word.match_type in (MatchType.ANCHOR, MatchType.EXACT)


def test_year_numeral_also_collapses_correctly():
    gold_words = ["back", "in", "twenty", "twenty", "four", "we", "shipped"]
    gold = _stt(gold_words)
    edited = _edited(["back", "in", "2024", "we", "shipped"])

    result = align(gold, edited)

    numeral_word = next(w for w in result if w.token.text == "2024")
    assert numeral_word.start == gold[2].start  # first "twenty"
    assert numeral_word.end == gold[4].end  # "four"


# --------------------------------------------------------------------------
# Sentence-reorder recovery (anchor chaining, see anchors.find_displaced_blocks)
#
# Reconstructs the concrete failure diagnosed via the benchmark: two whole
# sentences swap places (S1's sentence_reorder), and a common word (here
# "was") repeats on both sides of the swap. Before displaced-block recovery,
# find_anchors' single backbone chain dropped every anchor from BOTH
# swapped sentences (they mutually cross), leaving one huge unanchored
# segment that S3b's DP force-aligned sequentially — producing an
# 11.6-SECOND error on a real corpus document, matching "was" to the wrong
# occurrence entirely. These tests assert the specific properties that fix
# depends on.
# --------------------------------------------------------------------------


def _swapped_sentence_streams():
    # a list-literal fix here would trade readable, editable prose for an
    # unmaintainable wall of quoted words - noqa'd deliberately, not missed
    gold_words = (  # noqa: SIM905
        "there was no fanfare at all . Siobhan was the one who finally found "
        "the bug in the ingestion layer . nobody expected the migration to go "
        "this smoothly given how old the system was ."
    ).split()
    gold = _stt(gold_words)
    edited_words = (  # noqa: SIM905
        "there was no fanfare at all . nobody expected the migration to go "
        "this smoothly given how old the system was . Siobhan was the one "
        "who finally found the bug in the ingestion layer ."
    ).split()
    edited = _edited(edited_words)
    return gold_words, gold, edited_words, edited


def test_reordered_sentence_common_word_matches_its_own_occurrence_not_a_distant_one():
    """The core failure mode: a repeated common word ("was") inside a
    displaced sentence must match ITS OWN nearby gold occurrence — not an
    unrelated occurrence elsewhere in the document, which is what a single
    DP segment spanning both swapped sentences produced (11.6s off in the
    real corpus case this reproduces)."""
    gold_words, gold, edited_words, edited = _swapped_sentence_streams()
    result = align(gold, edited)

    # "Siobhan was the one" -> the edited "was" right after "Siobhan"
    # must land near gold's "Siobhan was" (index 8), not thousands of ms away.
    siobhan_edited_idx = edited_words.index("Siobhan")
    was_after_siobhan = result[siobhan_edited_idx + 1]
    assert was_after_siobhan.token.text == "was"
    true_start = gold[gold_words.index("was", 7)].start  # the "was" right after "Siobhan" in gold
    assert abs(was_after_siobhan.start - true_start) < 1.0  # well under 1s, not 11.6s


def test_reordered_sentence_no_error_exceeds_two_seconds():
    """Bounds the WHOLE document's worst-case error, not just the one
    word checked above — the fix must not just move the failure
    elsewhere in the same swapped region."""
    gold_words, gold, edited_words, edited = _swapped_sentence_streams()
    result = align(gold, edited)

    # Build true correspondence by finding each edited word's nearest
    # matching gold occurrence around its expected neighborhood — since
    # every word here is used at most twice, walk both streams to build
    # ground truth directly from the known construction.
    max_err = 0.0
    gi = 0
    gold_cf = [w.casefold() for w in gold_words]
    for ei, tok in enumerate(edited_words):
        while gi < len(gold_cf) and gold_cf[gi] != tok.casefold():
            gi += 1
        if gi >= len(gold_cf):
            continue
        true_start = gold[gi].start
        err = abs(result[ei].start - true_start)
        max_err = max(max_err, err)
        gi += 1
    assert max_err < 2.0


def test_reordered_sentence_words_far_from_the_swap_are_unaffected():
    """Content outside the swapped region (before/after both sentences)
    must still match exactly — the fix must be local to the displaced
    region, not a global behavior change."""
    _gold_words, gold, edited_words, edited = _swapped_sentence_streams()
    result = align(gold, edited)

    # "there was no fanfare at all ." — the leading, unmoved sentence.
    for i in range(7):
        assert result[i].token.text == edited_words[i]
        assert result[i].start == gold[i].start
        assert result[i].match_type in (MatchType.ANCHOR, MatchType.EXACT)


# ---------------------------------------------------------------------
# resolve_audio_order — the S3/S5 boundary contract
# ---------------------------------------------------------------------


def test_resolve_audio_order_on_unreordered_input_is_a_no_op_on_order():
    gold_words, gold, _edited_words, _unused_edited = _swapped_sentence_streams()
    # Use the UNREORDERED edited stream (== gold_words) as a control case.
    result = align(gold, _edited(gold_words))
    audio_order, issues = resolve_audio_order(result)
    assert [w.token.index for w in audio_order] == list(range(len(result)))
    assert issues == []


def test_resolve_audio_order_sorts_a_reordered_document_by_true_timestamp():
    _gold_words, gold, _edited_words, edited = _swapped_sentence_streams()
    result = align(gold, edited)
    audio_order, _issues = resolve_audio_order(result)
    starts = [w.start for w in audio_order]
    assert starts == sorted(starts)


def test_resolve_audio_order_flags_the_displaced_span_with_transposed_block():
    _gold_words, gold, _edited_words, edited = _swapped_sentence_streams()
    result = align(gold, edited)
    _audio_order, issues = resolve_audio_order(result)
    assert issues, "expected at least one TRANSPOSED_BLOCK for a document with a swapped sentence"
    assert all(i.code == QCCode.TRANSPOSED_BLOCK for i in issues)
    assert all(i.severity == "info" for i in issues)


def test_resolve_audio_order_preserves_document_order_via_token_index():
    """Nothing is lost by sorting — token.index (EditedToken's own field,
    carried on every AlignedWord) always lets a caller reconstruct the
    original document order from the audio-ordered output."""
    _gold_words, gold, _edited_words, edited = _swapped_sentence_streams()
    result = align(gold, edited)
    audio_order, _issues = resolve_audio_order(result)

    original_indices = sorted(w.token.index for w in result)
    reconstructed = sorted(audio_order, key=lambda w: w.token.index)
    assert [w.token.index for w in reconstructed] == original_indices
    assert [w.token.text for w in reconstructed] == [w.token.text for w in sorted(result, key=lambda w: w.token.index)]


def test_resolve_audio_order_empty_input():
    assert resolve_audio_order([]) == ([], [])


# ---------------------------------------------------------------------
# Interpolation happens in audio order, not edited order — the second bug
# found while verifying resolve_audio_order: sorting fixed ORDER, but
# interpolate_gaps still bounded a gap using edited-order neighbors, which
# can be seconds apart in audio time from a nearby displaced block. Fixed
# by resolving each segment's own interpolated placeholders locally
# (_dp_segment), bounded only by that segment's own real anchors, before
# they ever reach a flat cross-chain list.
# ---------------------------------------------------------------------


def _gap_adjacent_to_displaced_block_streams():
    """A backbone anchor immediately followed by an editorial-insertion-
    style gap (words with no clean match anywhere), immediately followed
    by a displaced block (a swapped later sentence). Before the fix, the
    gap's interpolated span was bounded using the displaced block's own
    anchor as a "neighbor" — audio-seconds away, not adjacent — producing
    a span wide enough to overlap the block's real, correctly-matched
    content."""
    gold_words = (  # noqa: SIM905
        "everyone remembered the failure modes clearly afterward . "
        "shipped the first version on a friday afternoon which was risky . "
        "nobody expected the migration to go this smoothly given how old the system was ."
    ).split()
    gold = _stt(gold_words)
    edited_words = (  # noqa: SIM905
        "everyone remembered the failure modes clearly afterward . "
        "totally unrelated inserted commentary here . "
        "nobody expected the migration to go this smoothly given how old the system was . "
        "shipped the first version on a friday afternoon which was risky ."
    ).split()
    edited = _edited(edited_words)
    return gold, edited


def test_interpolated_gap_never_overlaps_a_nearby_displaced_block():
    """The regression this whole fix is for: an interpolated gap sitting
    between the backbone and a displaced block must never inherit a span
    reaching into the displaced block's own (correctly, locally-resolved)
    real timing."""
    gold, edited = _gap_adjacent_to_displaced_block_streams()
    result = align(gold, edited)
    audio_order, _issues = resolve_audio_order(result)

    overlaps = [(a, b) for a, b in pairwise(audio_order) if b.start < a.end]
    assert not overlaps, f"word-level overlaps after sorting into audio order: {overlaps}"


def test_interpolated_words_are_never_wider_than_a_generous_bound():
    """An interpolated placeholder that used to bridge across a chain
    boundary could inherit a multi-second span (observed: 2.9s, in a
    document where every real word is well under 1s). Bounding locally
    means even a genuinely-unbounded orphan run (no anchor on one side)
    collapses to zero duration rather than spanning into unrelated
    content — so no interpolated word here should show an implausibly
    wide span."""
    gold, edited = _gap_adjacent_to_displaced_block_streams()
    result = align(gold, edited)
    for w in result:
        if w.match_type == MatchType.INTERPOLATED:
            assert w.end - w.start < 2.0, f"{w.token.text!r} has an implausibly wide interpolated span: {w.start}-{w.end}"
