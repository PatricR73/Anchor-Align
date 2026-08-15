"""S3a — anchor detection.

Finds long, rare words that appear exactly once, in the same order, in both
the STT stream and the edited transcript. These split the alignment problem
into short segments so S3b's DP matrix stays small.
"""

from __future__ import annotations

from collections import Counter

from anchor_align.models import NormalizedToken

MIN_ANCHOR_LENGTH = 5


def find_anchors(
    stt_tokens: list[NormalizedToken],
    edited_tokens: list[NormalizedToken],
    *,
    min_length: int = MIN_ANCHOR_LENGTH,
) -> list[tuple[int, int]]:
    """Return ordered (stt_index, edited_index) anchor pairs.

    A word qualifies if it's at least `min_length` characters (long enough
    that a coincidental exact match across unrelated words is unlikely) and
    occurs EXACTLY ONCE in each stream (a word appearing twice has no
    unique correspondence to pin down).

    Matching is on `normal` only, not `variants`: an anchor must be a
    maximally-confident fixed point, and a variant reading (a numeral's
    word-form, a contraction's expansion) is inherently a guess among
    readings.

    Candidates are restricted to a strictly monotonic subsequence in both
    streams via longest increasing subsequence — a crossing candidate is
    almost always a coincidental collision, not real reordering (S1's
    sentence_reorder moves a whole span, it doesn't interleave two
    overlapping anchors).
    """
    candidates = _anchor_candidates(stt_tokens, edited_tokens, min_length)
    return _longest_increasing_by_first(candidates)


def _anchor_candidates(
    stt_tokens: list[NormalizedToken], edited_tokens: list[NormalizedToken], min_length: int
) -> list[tuple[int, int]]:
    """Every (stt_index, edited_index) pair whose word is long+rare in both
    streams, sorted by edited_index — the raw candidate pool shared by
    `find_anchors` (which LIS-restricts it to one monotonic backbone) and
    `find_displaced_blocks` (which also chains the residual)."""
    stt_counts = Counter(t.normal for t in stt_tokens if len(t.normal) >= min_length)
    edited_counts = Counter(t.normal for t in edited_tokens if len(t.normal) >= min_length)

    stt_unique_pos = {
        t.normal: i
        for i, t in enumerate(stt_tokens)
        if len(t.normal) >= min_length and stt_counts[t.normal] == 1
    }

    candidates: list[tuple[int, int]] = []
    for j, t in enumerate(edited_tokens):
        if len(t.normal) < min_length or edited_counts[t.normal] != 1:
            continue
        stt_i = stt_unique_pos.get(t.normal)
        if stt_i is not None:
            candidates.append((stt_i, j))

    candidates.sort(key=lambda pair: pair[1])
    return candidates


MIN_DISPLACED_BLOCK_LENGTH = 3


def find_displaced_blocks(
    stt_tokens: list[NormalizedToken],
    edited_tokens: list[NormalizedToken],
    *,
    min_length: int = MIN_ANCHOR_LENGTH,
    min_chain_length: int = MIN_DISPLACED_BLOCK_LENGTH,
) -> tuple[list[tuple[int, int]], list[list[tuple[int, int]]]]:
    """Anchor chaining, as used in genome alignment (MUMmer, minimap2) to
    handle inversions/translocations a plain sequential aligner can't
    express.

    `find_anchors` keeps only the single longest monotonic chain (the
    "backbone") and drops every candidate that would have to cross it —
    correct for the backbone, but it means a whole relocated span (S1's
    sentence_reorder swapping two adjacent sentences) contributes NOTHING
    to segmentation: its anchors get dropped as "crossing", leaving one
    large unanchored gap that S3b's sequential DP then force-aligns into
    near-arbitrary long-distance mismatches on any repeated word.

    This chains the RESIDUAL (backbone-excluded) candidates: LIS again on
    what's left. A residual chain of length >= 3 that's itself internally
    strictly increasing in both streams is a DISPLACED BLOCK — real,
    self-contained content that moved as a unit, boundaries already known
    from the chain's own extent. Length < 3 is discarded: two residual
    points forming an "increasing pair" is what coincidence looks like,
    not evidence of a moved block. Repeats until no chain of length >= 3
    remains, so several displaced regions in one document are found
    independently.

    Returns (backbone, displaced_blocks), blocks ordered by each chain's
    first edited_index. Anything that doesn't chain into a coherent
    length->=3 block (partial reordering, single-word transpositions,
    deeply interleaved content) falls through to the pre-existing
    single-DP-segment behavior — an accepted, documented gap.
    """
    candidates = _anchor_candidates(stt_tokens, edited_tokens, min_length)
    backbone = _longest_increasing_by_first(candidates)
    backbone_set = set(backbone)
    residual = [c for c in candidates if c not in backbone_set]

    blocks: list[list[tuple[int, int]]] = []
    while True:
        residual.sort(key=lambda pair: pair[1])
        chain = _longest_increasing_by_first(residual)
        if len(chain) < min_chain_length:
            break
        blocks.append(chain)
        chain_set = set(chain)
        residual = [c for c in residual if c not in chain_set]

    blocks.sort(key=lambda block: block[0][1])
    return backbone, blocks


def _longest_increasing_by_first(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """`pairs` is sorted by the second coordinate (unique per pair, since
    each edited index appears at most once); return the longest subsequence
    whose FIRST coordinate is also strictly increasing. Patience-sorting
    LIS, O(n log n), reconstructed via parent pointers."""
    if not pairs:
        return []
    tails_idx: list[int] = []
    parents: list[int] = [-1] * len(pairs)
    for i, (a, _b) in enumerate(pairs):
        lo, hi = 0, len(tails_idx)
        while lo < hi:
            mid = (lo + hi) // 2
            if pairs[tails_idx[mid]][0] < a:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0:
            parents[i] = tails_idx[lo - 1]
        if lo == len(tails_idx):
            tails_idx.append(i)
        else:
            tails_idx[lo] = i

    result: list[tuple[int, int]] = []
    k = tails_idx[-1]
    while k != -1:
        result.append(pairs[k])
        k = parents[k]
    result.reverse()
    return result
