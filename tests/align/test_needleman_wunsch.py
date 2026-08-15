"""S3b — weighted Needleman-Wunsch alignment within an anchor-bounded
segment."""

from __future__ import annotations

from anchor_align.align.needleman_wunsch import align_segment, token_similarity
from anchor_align.models import NormalizedToken


def _tok(normal: str, *, variants=(), keys=()) -> NormalizedToken:
    return NormalizedToken(surface=normal, normal=normal, char_span=(0, 1), source_indices=(0,), variants=variants, keys=keys)


def test_identical_sequences_align_1to1():
    stt = [_tok(w) for w in ["the", "quick", "brown", "fox"]]
    edited = [_tok(w) for w in ["the", "quick", "brown", "fox"]]
    assert align_segment(stt, edited) == [(0, 0), (1, 1), (2, 2), (3, 3)]


def test_similar_enough_substituted_word_still_aligns_1to1():
    # "frade" is a plausible ASR near-miss of "frayed" — edit distance
    # alone doesn't clear MIN_MATCH_SIMILARITY, but a shared phonetic key
    # (what a real PhoneticEncoder would give this pair) pushes it over,
    # so it should still be accepted as one substitution.
    stt = [_tok("the"), _tok("frayed", keys=("FRT",)), _tok("brown"), _tok("fox")]
    edited = [_tok("the"), _tok("frade", keys=("FRT",)), _tok("brown"), _tok("fox")]
    pairs = align_segment(stt, edited)
    assert len(pairs) == 4
    assert all(s is not None and e is not None for s, e in pairs)


def test_genuinely_unrelated_substituted_word_becomes_a_gap_pair_not_a_forced_match():
    # "quick" and "slow" share almost nothing textually or phonetically —
    # below MIN_MATCH_SIMILARITY, so the DP must prefer two honest gaps
    # over a confident-looking but wrong substitution.
    stt = [_tok(w) for w in ["the", "quick", "brown", "fox"]]
    edited = [_tok(w) for w in ["the", "slow", "brown", "fox"]]
    pairs = align_segment(stt, edited)
    quick_deleted = any(s is not None and stt[s].normal == "quick" and e is None for s, e in pairs)
    slow_inserted = any(s is None and e is not None and edited[e].normal == "slow" for s, e in pairs)
    assert quick_deleted
    assert slow_inserted


def test_deleted_gold_word_produces_a_gap():
    stt = [_tok(w) for w in ["the", "quick", "brown", "fox"]]
    edited = [_tok(w) for w in ["the", "brown", "fox"]]
    pairs = align_segment(stt, edited)
    deletions = [p for p in pairs if p[1] is None]
    assert len(deletions) == 1
    assert stt[deletions[0][0]].normal == "quick"


def test_inserted_edited_word_produces_a_gap():
    stt = [_tok(w) for w in ["the", "brown", "fox"]]
    edited = [_tok(w) for w in ["the", "very", "brown", "fox"]]
    pairs = align_segment(stt, edited)
    insertions = [p for p in pairs if p[0] is None]
    assert len(insertions) == 1
    assert edited[insertions[0][1]].normal == "very"


def test_every_stt_and_edited_index_appears_exactly_once():
    stt = [_tok(w) for w in ["a", "b", "c", "d", "e"]]
    edited = [_tok(w) for w in ["a", "x", "c", "y", "e"]]
    pairs = align_segment(stt, edited)
    stt_indices = [s for s, _ in pairs if s is not None]
    edited_indices = [e for _, e in pairs if e is not None]
    assert sorted(stt_indices) == list(range(len(stt)))
    assert sorted(edited_indices) == list(range(len(edited)))


def test_empty_segments_produce_empty_alignment():
    assert align_segment([], []) == []


def test_all_gold_words_deleted_when_edited_is_empty():
    stt = [_tok(w) for w in ["a", "b", "c"]]
    pairs = align_segment(stt, [])
    assert pairs == [(0, None), (1, None), (2, None)]


def test_all_edited_words_inserted_when_gold_is_empty():
    edited = [_tok(w) for w in ["a", "b", "c"]]
    pairs = align_segment([], edited)
    assert pairs == [(None, 0), (None, 1), (None, 2)]


def test_token_similarity_identical_is_high():
    a, b = _tok("hello"), _tok("hello")
    assert token_similarity(a, b) == 0.6  # EDIT_WEIGHT * 1.0 + PHONETIC_WEIGHT * 0.0 (no keys)


def test_token_similarity_uses_best_variant_reading():
    a = _tok("twenty")
    with_variant = token_similarity(a, _tok("20%", variants=(("twenty", "percent"),)))
    without_variant = token_similarity(a, _tok("20%"))
    assert with_variant > without_variant  # "twenty" matches the variant reading much better than "20%" itself


def test_token_similarity_phonetic_overlap_contributes():
    a = _tok("frayed", keys=("FRT",))
    b = _tok("frade", keys=("FRT",))
    without_keys = token_similarity(_tok("frayed"), _tok("frade"))
    with_keys = token_similarity(a, b)
    assert with_keys > without_keys


def test_token_similarity_identical_words_are_not_phonetically_inflated():
    # Phonetic similarity supplements edit distance; an already-identical
    # pair scores EDIT_WEIGHT and must not be bumped to 1.0 — that uniform
    # +0.4 perturbation on exact pairs flips traceback ties between
    # equal-cost paths (see token_similarity's docstring).
    a = _tok("at", keys=("AT",))
    assert token_similarity(a, a) == 0.6
