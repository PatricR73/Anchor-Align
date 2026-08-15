"""S3c — interpolation for unmatched edited words.

Distributes timing proportionally by syllable count across the gap left by
words with no match from S3b.
"""

from __future__ import annotations

import re

from anchor_align.models import AlignedWord, MatchType

_VOWEL_GROUP = re.compile(r"[aeiouAEIOUăâîșțĂÂÎȘȚ]+")


def _syllable_estimate(text: str) -> int:
    """Crude vowel-group count, never zero — an all-consonant token like an
    acronym still gets a fair share of the gap rather than none."""
    return max(1, len(_VOWEL_GROUP.findall(text)))


def interpolate_gaps(aligned_words: list[AlignedWord]) -> list[AlignedWord]:
    """Fill in real timing for every AlignedWord whose `match_type` is
    INTERPOLATED (the caller's placeholder for "S3b found no match" — a
    zero-duration span at this point).

    A maximal RUN of INTERPOLATED words between two timed neighbors splits
    that neighbor pair's gap proportionally to each word's estimated
    syllable count — a 4-syllable word plausibly took longer to say than a
    1-syllable one. A run at the very start/end (no timed neighbor on one
    side) collapses to a zero-duration span pinned at the one neighbor that
    does exist. match_type stays INTERPOLATED after this runs; only
    start/end change — `AlignmentMetrics.measured_word_count` relies on
    match_type, not duration, to know which words have real evidence.
    """
    result = list(aligned_words)
    n = len(result)
    i = 0
    while i < n:
        if result[i].match_type != MatchType.INTERPOLATED:
            i += 1
            continue
        j = i
        while j < n and result[j].match_type == MatchType.INTERPOLATED:
            j += 1

        left = result[i - 1] if i > 0 else None
        right = result[j] if j < n else None
        if left is not None:
            gap_start = left.end
        elif right is not None:
            gap_start = right.start
        else:
            gap_start = 0.0
        if right is not None:
            gap_end = right.start
        elif left is not None:
            gap_end = left.end
        else:
            gap_end = 0.0

        span = max(0.0, gap_end - gap_start)
        weights = [_syllable_estimate(result[k].token.text) for k in range(i, j)]
        total_weight = sum(weights)

        cursor = gap_start
        for k, w in zip(range(i, j), weights):
            share = span * (w / total_weight) if total_weight else 0.0
            new_start = cursor
            new_end = cursor + share
            result[k] = result[k].model_copy(update={"start": new_start, "end": new_end})
            cursor = new_end

        i = j
    return result
