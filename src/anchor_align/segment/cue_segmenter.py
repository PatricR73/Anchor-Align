"""S5 — segmentation of aligned words into VTT/SRT cues.

Constraints (max 2 lines, max 42 chars/line, 1-7s, max 21 chars/s, break
on natural phrase boundaries via pysbd, no overlaps) conflict with each
other, so break points are chosen by dynamic programming over a cost
function rather than greedily.

DP shape: dp[i] = (min cost to segment words[0:i], best predecessor index).
Transition dp[i] -> dp[j] considers cue candidate words[i:j]. A candidate
is HARD-infeasible (excluded from the DP graph entirely, cost=inf) if it
can't be wrapped into <=2 lines of <=42 chars each, or if its raw duration
exceeds MAX_DURATION_S. Duration-too-short and CPS-too-high are
SOFT-penalized instead of excluded: excluding them outright can leave the
DP with no path to the end (e.g. a short trailing utterance with nothing
left to merge into), and a heavily-penalized-but-legal cue beats an
unreachable graph. Ending a cue at a pysbd sentence boundary is rewarded
with a small bonus, and a per-cue fixed cost discourages fragmenting into
more, shorter cues than the constraints actually require.
"""

from __future__ import annotations

import bisect
from itertools import pairwise

import pysbd

from anchor_align.caption_constraints import MAX_DURATION_S, MAX_LINE_CHARS, MAX_LINES, MIN_DURATION_S, MAX_CPS
from anchor_align.models import AlignedWord, Cue, QCCode, QCIssue

# Soft-cost weights. Relative magnitude matters more than any single value:
# a hard-infeasible candidate is excluded outright, so these only trade off
# among candidates that are all legal to build — the penalties just need to
# dominate the small per-cue and balance costs so the DP won't prefer a
# QC-violating cue purely to save a cue or to look tidier, while still
# being finite so a forced case (no feasible alternative) is chosen over no
# path at all.
SHORT_DURATION_PENALTY_PER_S = 1000.0
CPS_OVER_PENALTY_PER_UNIT = 50.0
SENTENCE_BOUNDARY_BONUS = 5.0
PER_CUE_COST = 1.0
TARGET_DURATION_S = 3.5
DURATION_BALANCE_WEIGHT = 0.05


def _wrap_lines(texts: list[str]) -> list[str] | None:
    """Wrap `texts` (already-ordered word strings) into at most MAX_LINES
    lines of at most MAX_LINE_CHARS characters each, or None if no such
    wrapping exists (including the degenerate case of a single word longer
    than MAX_LINE_CHARS, which no wrapping can fix).

    Single line if the whole run fits — line count doesn't affect CPS
    (that's total chars / duration regardless of line count). When two
    lines are needed, the split point balances the two lines' lengths
    (minimize the longer of the two), the standard subtitling convention.
    """
    full = " ".join(texts)
    if len(full) <= MAX_LINE_CHARS:
        return [full]
    if len(texts) < 2:
        return None  # one over-long word; no split can help it

    best: list[str] | None = None
    best_longer = None
    for split in range(1, len(texts)):
        line1 = " ".join(texts[:split])
        line2 = " ".join(texts[split:])
        if len(line1) > MAX_LINE_CHARS or len(line2) > MAX_LINE_CHARS:
            continue
        longer = max(len(line1), len(line2))
        if best_longer is None or longer < best_longer:
            best_longer = longer
            best = [line1, line2]
    return best


def _sentence_end_word_indices(words: list[AlignedWord]) -> set[int]:
    """Word indices (into `words`) that end a pysbd-detected sentence —
    preferred (bonus-weighted) cue break points. Built by concatenating
    every word's text with single-space separators and mapping pysbd's
    character-offset segments back onto word boundaries; approximate by
    construction (pysbd works on the joined surface text, not our word
    index space), which is fine for a soft preference."""
    if not words:
        return set()

    joined_parts: list[str] = []
    word_end_offsets: list[int] = []
    cursor = 0
    for w in words:
        joined_parts.append(w.token.text)
        cursor += len(w.token.text)
        word_end_offsets.append(cursor)
        cursor += 1  # the space separator added below
        joined_parts.append(" ")
    joined = "".join(joined_parts)

    segmenter = pysbd.Segmenter(language="en", clean=False)
    segments = segmenter.segment(joined)

    boundary_positions: list[int] = []
    consumed = 0
    for seg in segments:
        consumed += len(seg)
        boundary_positions.append(consumed)

    result: set[int] = set()
    for boundary in boundary_positions:
        # first word whose own end offset reaches this sentence boundary
        idx = bisect.bisect_left(word_end_offsets, boundary)
        if idx < len(words):
            result.add(idx)
    return result


def _candidate_cue(
    words: list[AlignedWord], i: int, j: int, sentence_ends: set[int]
) -> tuple[list[str], float] | None:
    """Build the cue for words[i:j) (half-open), or None if hard-infeasible.
    Returns (wrapped lines, soft cost) for a feasible candidate."""
    lines = _wrap_lines([w.token.text for w in words[i:j]])
    if lines is None:
        return None

    duration = words[j - 1].end - words[i].start
    if duration > MAX_DURATION_S:
        return None

    # CPS is evaluated against the duration this cue will actually have
    # AFTER _pad_duration runs, not its raw word-timing duration — a short
    # cue's real output duration is whichever is larger, so scoring on the
    # raw (shorter) duration would overstate its CPS cost and bias the DP
    # away from short cues that padding will fix. (Padding is bounded by
    # the next cue's start, so this is an estimate, not a guarantee.)
    char_count = sum(len(line) for line in lines)
    cps_duration = max(duration, MIN_DURATION_S)
    cps = char_count / cps_duration if cps_duration > 0 else float("inf")

    cost = PER_CUE_COST
    if duration < MIN_DURATION_S:
        cost += (MIN_DURATION_S - duration) * SHORT_DURATION_PENALTY_PER_S
    if cps > MAX_CPS:
        cost += (cps - MAX_CPS) * CPS_OVER_PENALTY_PER_UNIT
    cost += DURATION_BALANCE_WEIGHT * (duration - TARGET_DURATION_S) ** 2
    if (j - 1) in sentence_ends:
        cost -= SENTENCE_BOUNDARY_BONUS

    return lines, cost


def _pad_duration(cues: list[tuple[float, float, list[str]]]) -> list[tuple[float, float, list[str]]]:
    """Extend each cue's `end` up to MIN_DURATION_S where the source word
    timing left it short — borrowing only up to the next cue's `start` (or
    freely, for the last cue), so this can never introduce an overlap.
    Some genuinely-tight input can still end up short after this; that
    residual case is left for QC to report, not silently hidden here."""
    padded: list[tuple[float, float, list[str]]] = []
    for idx, (start, end, lines) in enumerate(cues):
        if end - start < MIN_DURATION_S:
            ceiling = cues[idx + 1][0] if idx + 1 < len(cues) else start + MIN_DURATION_S
            end = min(max(end, start + MIN_DURATION_S), ceiling) if ceiling > start else end
        padded.append((start, end, lines))
    return padded


def segment_into_cues(words: list[AlignedWord]) -> tuple[list[Cue], list[QCIssue]]:
    """Segment `words` into caption cues via dynamic programming — see the
    module docstring for the cost model. `Cue.word_span` is the exact
    [start, end) range into `words` (this same list) that produced each
    cue, per `Cue`'s contract. `Cue.index` is 1-based sequential in output
    order, renumbered to skip any cue dropped below.

    Returns `(cues, issues)`. `issues` currently only ever contains
    ZERO_DURATION_SPAN entries: a candidate cue whose words all landed at
    the exact same instant (start == end even after `_pad_duration`, which
    correctly declined to borrow room that doesn't exist against the next
    cue's start) is not constructed as a `Cue` at all — `Cue`'s own
    `end > start` validator is intentionally strict, so a fake minimum-
    width span is not invented here; the words are dropped from cue output
    and flagged for human review instead.

    PRECONDITION: `words` must already be in AUDIO order (non-decreasing
    `start`) — the S3/S5 boundary contract, enforced by
    `align.aligner.resolve_audio_order`, which every caller MUST run
    align()'s output through before calling this function. Checked below,
    not assumed: a caller that skips resolve_audio_order gets a clear
    error here, not silently wrong DP output.
    """
    n = len(words)
    if n == 0:
        return [], []
    for a, b in pairwise(words):
        if b.start < a.start:
            raise ValueError(
                f"words is not sorted by start ({b.start} < {a.start}) — segment_into_cues requires "
                "audio-ordered input; run align()'s output through "
                "anchor_align.align.aligner.resolve_audio_order first"
            )

    sentence_ends = _sentence_end_word_indices(words)

    # dp_cost[i]: min cost to segment words[0:i]; dp_prev[i]: predecessor
    # index j such that the best path to i came via a cue words[j:i].
    dp_cost: list[float] = [float("inf")] * (n + 1)
    dp_prev: list[int] = [-1] * (n + 1)
    dp_lines: list[list[str] | None] = [None] * (n + 1)
    dp_cost[0] = 0.0

    for i in range(n):
        if dp_cost[i] == float("inf"):
            continue
        for j in range(i + 1, n + 1):
            # Duration-based window bound: once even the tightest possible
            # reading of words[i:j) exceeds MAX_DURATION_S, every larger j
            # will too — guaranteed by the audio-order precondition above.
            if words[j - 1].start - words[i].start > MAX_DURATION_S:
                break
            candidate = _candidate_cue(words, i, j, sentence_ends)
            if candidate is None:
                continue
            lines, cue_cost = candidate
            total = dp_cost[i] + cue_cost
            if total < dp_cost[j]:
                dp_cost[j] = total
                dp_prev[j] = i
                dp_lines[j] = lines

    if dp_cost[n] == float("inf"):
        # No wrapping exists even one word at a time — only possible if a
        # single word alone is already unwrappable, i.e. longer than
        # MAX_LINE_CHARS. Fall back to one cue per word, unpadded on
        # length, so output still exists; QC will (correctly) flag it.
        boundaries = list(range(n + 1))
        lines_per_cue = [[w.token.text] for w in words]
    else:
        boundaries = []
        lines_per_cue = []
        k = n
        while k > 0:
            boundaries.append(k)
            lines_per_cue.append(dp_lines[k] or [])
            k = dp_prev[k]
        boundaries.append(0)
        boundaries.reverse()
        lines_per_cue.reverse()

    raw_cues: list[tuple[float, float, list[str]]] = []
    for idx in range(len(boundaries) - 1):
        i, j = boundaries[idx], boundaries[idx + 1]
        raw_cues.append((words[i].start, words[j - 1].end, lines_per_cue[idx]))

    raw_cues = _pad_duration(raw_cues)

    cues: list[Cue] = []
    issues: list[QCIssue] = []
    for idx, (start, end, lines) in enumerate(raw_cues):
        i, j = boundaries[idx], boundaries[idx + 1]
        if end <= start:
            issues.append(
                QCIssue(
                    severity="error",
                    code=QCCode.ZERO_DURATION_SPAN,
                    message=(
                        f"words[{i}:{j}] ({' '.join(w.token.text for w in words[i:j])!r}) all land at "
                        f"the same instant ({start}s) with no room to borrow before the next cue — "
                        "dropped from cue output, needs human review"
                    ),
                    cue_index=None,
                )
            )
            continue
        cues.append(Cue(index=len(cues) + 1, start=start, end=end, lines=lines, word_span=(i, j)))

    return cues, issues
