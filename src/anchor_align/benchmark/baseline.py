"""S4 — naive baseline (difflib.SequenceMatcher) as the line the real
aligner has to beat in the benchmark plots.

SequenceMatcher rather than a single forward pointer: matching blocks are
found globally, so one unmatchable edited token (an insertion with no gold
source, a substitution the baseline can't recognize) can't strand the rest
of the document the way a greedy forward scan can.
"""

from __future__ import annotations

import difflib

from anchor_align.models import AlignedWord, EditedToken, MatchType, STTWord


def align_baseline(
    stt_words: list[STTWord], edited_tokens: list[EditedToken]
) -> list[AlignedWord]:
    """Match edited tokens to gold STT words by casefolded text via
    SequenceMatcher; interpolate the gaps between matches linearly.

    Every edited token gets an AlignedWord — matched ones as EXACT with
    confidence 1.0, gaps as INTERPOLATED with confidence 0.0 (this baseline
    has no real evidence for their position, only the surrounding matches'
    timing) — so the output has a 1:1 shape with `edited_tokens` and can be
    scored the same way a real aligner's output would be.
    """
    if not edited_tokens:
        return []

    gold_texts = [w.text.casefold() for w in stt_words]
    edited_texts = [t.text.casefold() for t in edited_tokens]
    matcher = difflib.SequenceMatcher(None, gold_texts, edited_texts, autojunk=False)

    matched_gold: dict[int, int] = {}
    for gold_start, edited_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            matched_gold[edited_start + offset] = gold_start + offset

    n = len(edited_tokens)
    result: list[AlignedWord | None] = [None] * n
    for i, gi in matched_gold.items():
        result[i] = AlignedWord(
            token=edited_tokens[i],
            start=stt_words[gi].start,
            end=stt_words[gi].end,
            match_type=MatchType.EXACT,
            confidence=1.0,
        )

    matched_positions = sorted(matched_gold)
    fallback_start = stt_words[0].start if stt_words else 0.0
    fallback_end = stt_words[-1].end if stt_words else 0.0
    for i in range(n):
        if result[i] is not None:
            continue
        left = max((p for p in matched_positions if p < i), default=None)
        right = min((p for p in matched_positions if p > i), default=None)
        left_word = result[left] if left is not None else None
        right_word = result[right] if right is not None else None
        span_start = left_word.end if left_word is not None else fallback_start
        span_end = right_word.start if right_word is not None else fallback_end
        result[i] = AlignedWord(
            token=edited_tokens[i],
            start=min(span_start, span_end),
            end=max(span_start, span_end),
            match_type=MatchType.INTERPOLATED,
            confidence=0.0,
        )

    return [w for w in result if w is not None]
