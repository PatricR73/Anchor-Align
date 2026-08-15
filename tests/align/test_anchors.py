"""S3a — anchor detection: long, rare, same-order words in both streams."""

from __future__ import annotations

from anchor_align.align.anchors import find_anchors, find_displaced_blocks
from anchor_align.models import NormalizedToken


def _tok(i: int, normal: str) -> NormalizedToken:
    return NormalizedToken(surface=normal, normal=normal, char_span=(i, i + 1), source_indices=(i,))


def _toks(words: list[str]) -> list[NormalizedToken]:
    return [_tok(i, w) for i, w in enumerate(words)]


def test_long_unique_words_become_anchors():
    stt = _toks(["the", "quick", "brown", "fox", "jumps"])
    edited = _toks(["a", "quick", "brown", "fox", "leaps"])
    assert find_anchors(stt, edited) == [(1, 1), (2, 2)]


def test_short_words_are_never_anchors():
    stt = _toks(["fox", "cat", "dog"])
    edited = _toks(["fox", "cat", "dog"])
    assert find_anchors(stt, edited) == []


def test_word_repeated_in_stt_stream_is_not_an_anchor():
    stt = _toks(["hello", "world", "hello"])
    edited = _toks(["hello", "world"])
    anchors = find_anchors(stt, edited)
    assert not any(stt[i].normal == "hello" for i, _ in anchors)


def test_word_repeated_in_edited_stream_is_not_an_anchor():
    stt = _toks(["hello", "world"])
    edited = _toks(["hello", "world", "hello"])
    anchors = find_anchors(stt, edited)
    assert not any(edited[j].normal == "hello" for _, j in anchors)


def test_word_missing_from_one_stream_is_not_an_anchor():
    stt = _toks(["morning", "friend"])
    edited = _toks(["evening", "world"])
    assert find_anchors(stt, edited) == []


def test_out_of_order_candidate_is_dropped_by_lis():
    # "welcome" and "morning" appear in swapped relative order between
    # streams — a real crossing pair, must not both survive.
    stt = _toks(["welcome", "friend", "morning"])
    edited = _toks(["morning", "friend", "welcome"])
    anchors = find_anchors(stt, edited)
    # LIS keeps at most one of the two crossing candidates.
    assert len(anchors) <= 1


def test_anchors_are_strictly_increasing_in_both_coordinates():
    stt = _toks(["alpha", "bravo", "charlie", "delta", "echo"])
    edited = _toks(["zulu", "alpha", "yankee", "bravo", "xray", "charlie", "delta", "whiskey", "echo"])
    anchors = find_anchors(stt, edited)
    stt_idx = [a for a, _ in anchors]
    edited_idx = [b for _, b in anchors]
    assert stt_idx == sorted(stt_idx)
    assert edited_idx == sorted(edited_idx)
    assert len(set(stt_idx)) == len(stt_idx)
    assert len(set(edited_idx)) == len(edited_idx)


def test_empty_streams_yield_no_anchors():
    assert find_anchors([], []) == []
    assert find_anchors(_toks(["hello"]), []) == []
    assert find_anchors([], _toks(["hello"])) == []


def test_custom_min_length_threshold():
    stt = _toks(["fox", "wolf"])
    edited = _toks(["fox", "wolf"])
    assert find_anchors(stt, edited, min_length=3) == [(0, 0), (1, 1)]
    assert find_anchors(stt, edited, min_length=10) == []


# ---------------------------------------------------------------------
# find_displaced_blocks — anchor chaining (MUMmer/minimap2-style) for
# whole relocated spans (e.g. S1's sentence_reorder swapping two
# adjacent sentences), which find_anchors' single backbone chain has to
# drop entirely since keeping them would cross the backbone.
# ---------------------------------------------------------------------


def test_no_reordering_yields_backbone_only_no_blocks():
    stt = _toks(["welcome", "morning", "everyone", "listening", "carefully"])
    edited = _toks(["welcome", "morning", "everyone", "listening", "carefully"])
    backbone, blocks = find_displaced_blocks(stt, edited)
    assert backbone == find_anchors(stt, edited)
    assert blocks == []


_SWAPPED_TRIPLE_STT = ["opening", "remarks", "welcome", "alpha", "bravo", "charlie", "delta", "engine", "foxtrot", "closing"]
_SWAPPED_TRIPLE_EDITED = ["opening", "remarks", "welcome", "delta", "engine", "foxtrot", "alpha", "bravo", "charlie", "closing"]


def test_two_swapped_blocks_of_three_are_both_recovered():
    # Two three-word "sentences" (each internally long+rare+unique) swap
    # places in the edited stream — the minimal case find_anchors alone
    # cannot represent (both halves would cross the other under LIS).
    stt = _toks(_SWAPPED_TRIPLE_STT)
    edited = _toks(_SWAPPED_TRIPLE_EDITED)
    backbone, blocks = find_displaced_blocks(stt, edited)

    assert len(blocks) == 1
    block = blocks[0]
    assert len(block) == 3
    # the whole block is internally strictly increasing in both streams
    stt_idx = [s for s, _ in block]
    edited_idx = [e for _, e in block]
    assert stt_idx == sorted(stt_idx)
    assert edited_idx == sorted(edited_idx)
    # the displaced content is exactly "delta"/"engine"/"foxtrot"
    assert {stt[s].normal for s, _ in block} == {"delta", "engine", "foxtrot"}
    # "opening"/"remarks"/"welcome"/"alpha"/"bravo"/"charlie"/"closing"
    # (unmoved relative to each other) stay on the backbone
    assert not any(stt[s].normal in ("delta", "engine", "foxtrot") for s, _ in backbone)


def test_short_residual_chain_below_threshold_is_not_a_displaced_block():
    # A single adjacent-pair transposition only ever excludes ONE
    # candidate from LIS (length n-1, not n-2) — below
    # MIN_DISPLACED_BLOCK_LENGTH (3), must not be promoted to a block.
    stt = _toks(["welcome", "alpha", "bravo", "morning", "listening"])
    edited = _toks(["welcome", "bravo", "alpha", "morning", "listening"])
    backbone, blocks = find_displaced_blocks(stt, edited)
    assert blocks == []
    assert len(backbone) == 4  # one of alpha/bravo excluded, not both


def test_two_separate_displaced_blocks_both_recovered_and_ordered():
    # Two independent three-word blocks (far apart, unrelated words) swap
    # ends of the document; a large unmoved middle section stays backbone.
    stt = _toks(
        ["alpha1", "alpha2", "alpha3", "middle1", "middle2", "middle3", "beta1x", "beta2x", "beta3x",
         "middle4", "middle5", "middle6", "gamma1", "gamma2", "gamma3"]
    )
    edited = _toks(
        ["gamma1", "gamma2", "gamma3", "middle1", "middle2", "middle3", "beta1x", "beta2x", "beta3x",
         "middle4", "middle5", "middle6", "alpha1", "alpha2", "alpha3"]
    )
    _backbone, blocks = find_displaced_blocks(stt, edited)

    assert len(blocks) == 2
    # ordered by first edited_index: the gamma-block (now at the front of
    # the edited stream) comes before the alpha-block (now at the end)
    assert blocks[0][0][1] < blocks[1][0][1]
    assert {stt[s].normal for s, _ in blocks[0]} == {"gamma1", "gamma2", "gamma3"}
    assert {stt[s].normal for s, _ in blocks[1]} == {"alpha1", "alpha2", "alpha3"}


def test_displaced_block_candidates_are_excluded_from_backbone():
    stt = _toks(_SWAPPED_TRIPLE_STT)
    edited = _toks(_SWAPPED_TRIPLE_EDITED)
    backbone, blocks = find_displaced_blocks(stt, edited)
    block_edited_indices = {e for block in blocks for _, e in block}
    backbone_edited_indices = {e for _, e in backbone}
    assert block_edited_indices.isdisjoint(backbone_edited_indices)


def test_custom_min_chain_length_allows_shorter_blocks():
    # With the threshold lowered to 2, the single excluded candidate from
    # a plain adjacent-pair transposition now DOES qualify as a block.
    stt = _toks(["welcome", "alpha", "bravo", "morning", "listening"])
    edited = _toks(["welcome", "bravo", "alpha", "morning", "listening"])
    _backbone, blocks = find_displaced_blocks(stt, edited, min_chain_length=1)
    assert len(blocks) == 1
    assert len(blocks[0]) == 1
