"""S4 — drift metric: does boundary error grow over a document's length?

AlignmentMetrics' pooled mean/p95 treats every token equally regardless of
its position in the file — a method with uniformly-high error and one whose
error grows linearly toward the end average to the same pooled number, but
only the second is what a client means by "does it still line up by minute
40". compute_drift splits by TIMELINE (not token count) into the first
`1 - tail_fraction` of the document's duration ("body") and the final
`tail_fraction` ("tail"), and reports mean/max separately for each —
exactly the comparison a purely sequential matcher (no periodic
re-anchoring) should structurally lose and anchoring should win.
"""

from __future__ import annotations

import statistics

from anchor_align.models import AlignedWord, DriftMetrics, MatchType, STTWord, TokenMapping

TAIL_FRACTION = 0.1


def compute_drift(
    predicted: list[AlignedWord],
    stt_words: list[STTWord],
    mapping: tuple[TokenMapping, ...],
    *,
    tail_fraction: float = TAIL_FRACTION,
) -> DriftMetrics:
    """Same scoring contract as `compute_metrics` (runner.py): score
    `predicted[i]` against `mapping[i]`'s TRUE gold indices (not whatever
    `predicted[i].token` claims), skipping INTERPOLATED predictions and
    true INSERTED tokens. Split into body/tail by the TRUE word's timeline
    position — a document isn't corrupted evenly by token count, so a
    token-index split wouldn't reliably land the last `tail_fraction` of
    the file's actual duration in the tail bucket.

    Raises ValueError if either bucket ends up with zero scorable words —
    a degenerate split has nothing meaningful to report, the same design
    choice compute_metrics makes for the whole-document case.
    """
    if len(predicted) != len(mapping):
        raise ValueError(
            f"predicted has {len(predicted)} entries but mapping has {len(mapping)} — "
            "they must describe the same edited-token stream, 1:1"
        )
    if not stt_words:
        raise ValueError("stt_words is empty — no timeline to split into body/tail")
    if not (0.0 < tail_fraction < 1.0):
        raise ValueError(f"tail_fraction must be in (0, 1), got {tail_fraction}")

    total_duration = max(w.end for w in stt_words)
    cutoff = total_duration * (1 - tail_fraction)

    body_errors: list[float] = []
    tail_errors: list[float] = []

    for pred, m in zip(predicted, mapping):
        if pred.match_type == MatchType.INTERPOLATED or not m.gold_indices:
            continue
        true_start = min(stt_words[gi].start for gi in m.gold_indices)
        true_end = max(stt_words[gi].end for gi in m.gold_indices)
        start_err = abs(pred.start - true_start) * 1000
        end_err = abs(pred.end - true_end) * 1000
        bucket = tail_errors if true_start >= cutoff else body_errors
        bucket.append(start_err)
        bucket.append(end_err)

    if not body_errors:
        raise ValueError("no scorable predictions in the document body (first "
                          f"{(1 - tail_fraction) * 100:.0f}% of the timeline)")
    if not tail_errors:
        raise ValueError(
            f"no scorable predictions in the document tail (final {tail_fraction * 100:.0f}% "
            "of the timeline) — the document may be too short, or too heavily corrupted near "
            "the end, for a meaningful drift comparison"
        )

    return DriftMetrics(
        body_mean_abs_error_ms=statistics.mean(body_errors),
        body_max_abs_error_ms=max(body_errors),
        body_measured_count=len(body_errors) // 2,
        tail_mean_abs_error_ms=statistics.mean(tail_errors),
        tail_max_abs_error_ms=max(tail_errors),
        tail_measured_count=len(tail_errors) // 2,
    )


def document_has_reorder(effective_config: tuple[tuple[str, float], ...]) -> bool:
    """True iff `sentence_reorder` actually fired for this corrupt() run —
    read from `CorruptionManifest.effective_config`, which records what was
    ACHIEVED, not just what was requested at this `level`. Callers should
    split on this and report both, not blend reorder-affected and
    reorder-free documents into one number.
    """
    return dict(effective_config).get("sentence_reorder", 0.0) > 0.0
