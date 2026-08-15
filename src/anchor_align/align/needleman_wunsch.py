"""S3b — weighted Needleman-Wunsch alignment within an anchor-bounded
segment.

Substitution cost is a blend of edit distance (RapidFuzz) and phonetic
similarity — matching `NormalizedToken.keys`, produced by whichever
`PhoneticEncoder` normalization was configured with. Operates on NumPy
matrices; each segment is small (20-50 words) thanks to S3a's anchoring.
"""

from __future__ import annotations

import numpy as np
from rapidfuzz.distance import Levenshtein

from anchor_align.models import NormalizedToken

GAP_PENALTY = 1.0
EDIT_WEIGHT = 0.6
PHONETIC_WEIGHT = 0.4

# token_similarity is bounded to [0, 1], and 0 is not "no relationship" —
# it's "as dissimilar as this scoring can express", still > -2*GAP_PENALTY
# (leaving both words as a deletion+insertion pair). Left alone, the DP
# would ALWAYS prefer even a near-zero-similarity substitution over
# correctly declining to match. MIN_MATCH_SIMILARITY makes a bad
# substitution actively worse than a double-gap, so the DP only proposes a
# substitution it has real textual/phonetic grounds for.
MIN_MATCH_SIMILARITY = 0.5
REJECTED_SUB_SCORE = -2 * GAP_PENALTY - 1.0


def _readings(token: NormalizedToken) -> list[str]:
    """Every candidate string this token could plausibly be compared
    against: its canonical `normal` form plus each `variants` entry joined
    into a single string — a numeral's word-form reading or a
    contraction's expansion gets the same shot at matching as the
    canonical form."""
    return [token.normal, *(" ".join(v) for v in token.variants)]


def token_similarity(a: NormalizedToken, b: NormalizedToken) -> float:
    """1.0 = as identical as this scoring can express, 0.0 = totally
    different. The best pairing across every reading on both sides, blended
    with phonetic key overlap (any of one side's `keys` matching any of the
    other's; an empty `keys` tuple contributes 0, not a false match)."""
    edit_sim = max(
        Levenshtein.normalized_similarity(x, y) for x in _readings(a) for y in _readings(b)
    )
    phonetic_sim = 1.0 if (a.keys and b.keys and set(a.keys) & set(b.keys)) else 0.0
    return EDIT_WEIGHT * edit_sim + PHONETIC_WEIGHT * phonetic_sim


def _substitution_score(a: NormalizedToken, b: NormalizedToken) -> float:
    """`token_similarity`, rejected down to a score worse than any gap
    combination, so the DP recurrence never special-cases "is this
    substitution actually any good"."""
    sim = token_similarity(a, b)
    return sim if sim >= MIN_MATCH_SIMILARITY else REJECTED_SUB_SCORE


def align_segment(
    stt_segment: list[NormalizedToken], edited_segment: list[NormalizedToken]
) -> list[tuple[int | None, int | None]]:
    """Return ordered (stt_index, edited_index) pairs; either side may be
    None. Indices are LOCAL to the input segments — the caller offsets them
    back into the full streams.

    Standard global-alignment DP: a substitution scores `_substitution_score`
    (rejected below MIN_MATCH_SIMILARITY), a gap costs GAP_PENALTY. On a tie
    substitution wins, then deletion, then insertion — an arbitrary but
    fixed tie-break, needed for deterministic output.
    """
    n, m = len(stt_segment), len(edited_segment)
    score = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        score[i, 0] = -i * GAP_PENALTY
    for j in range(1, m + 1):
        score[0, j] = -j * GAP_PENALTY

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = score[i - 1, j - 1] + _substitution_score(stt_segment[i - 1], edited_segment[j - 1])
            delete = score[i - 1, j] - GAP_PENALTY
            insert = score[i, j - 1] - GAP_PENALTY
            score[i, j] = max(sub, delete, insert)

    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and score[i, j] == score[i - 1, j - 1] + _substitution_score(stt_segment[i - 1], edited_segment[j - 1])
        ):
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and score[i, j] == score[i - 1, j] - GAP_PENALTY:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1

    pairs.reverse()
    return pairs
