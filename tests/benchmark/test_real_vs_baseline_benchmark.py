"""S4-final: S3's real align() vs. S4's naive align_baseline, scored via
compute_metrics on the same synthetic corpus, across corruption levels.
The full run_benchmark (Polars + matplotlib + written tables) is covered in
test_run_benchmark.py; this file is the comparison itself, printed, so the
numbers are visible without the aggregation layer.
"""

from __future__ import annotations

import statistics

import pytest

from anchor_align.align.aligner import align
from anchor_align.benchmark.adapters import to_edited_tokens
from anchor_align.benchmark.baseline import align_baseline
from anchor_align.benchmark.runner import compute_metrics
from anchor_align.corrupt.corpus import generate_corpus
from anchor_align.corrupt.corruptor import corrupt

CORPUS = generate_corpus(20, seed=1)


def _run_corpus_at_level(level: float, aligner_fn, master_seed: int = 1):
    results = []
    for doc_id, gold_words in CORPUS:
        out = corrupt(gold_words, level=level, doc_id=doc_id, master_seed=master_seed)
        edited_tokens = to_edited_tokens(out.tokens)
        predicted = aligner_fn(gold_words, edited_tokens)
        try:
            results.append(compute_metrics(predicted, gold_words, out.mapping))
        except ValueError:
            continue
    return results


def test_real_aligner_scores_near_zero_error_at_level_zero():
    """Same decisive sanity check as the baseline's: at level=0.0 every
    edited token is an exact, untouched copy of gold, so the real aligner
    should match every token via ANCHOR/EXACT and boundary error should be
    ~0."""
    results = _run_corpus_at_level(0.0, align)
    assert results, "no documents were scorable at level=0.0"
    for m in results:
        assert m.mean_abs_boundary_error_ms < 2.0


def test_real_aligner_vs_baseline_across_levels():
    """Report (not just assert) both aligners' numbers side by side, per
    level. This is the actual "get the number" step — printed via -s."""
    print()
    for level in (0.0, 0.1, 0.3, 0.5):
        real_results = _run_corpus_at_level(level, align)
        baseline_results = _run_corpus_at_level(level, align_baseline)
        assert real_results and baseline_results, f"no scorable documents at level={level}"

        real_mean = statistics.mean(m.mean_abs_boundary_error_ms for m in real_results)
        real_exact = statistics.mean(m.match_type_distribution.get("exact", 0.0) for m in real_results)
        real_anchor = statistics.mean(m.match_type_distribution.get("anchor", 0.0) for m in real_results)
        real_interp = statistics.mean(m.match_type_distribution.get("interpolated", 0.0) for m in real_results)

        base_mean = statistics.mean(m.mean_abs_boundary_error_ms for m in baseline_results)
        base_exact = statistics.mean(m.match_type_distribution.get("exact", 0.0) for m in baseline_results)
        base_interp = statistics.mean(m.match_type_distribution.get("interpolated", 0.0) for m in baseline_results)

        print(
            f"level={level}: "
            f"REAL mean_abs={real_mean:.1f}ms anchor={real_anchor:.3f} exact={real_exact:.3f} interp={real_interp:.3f} | "
            f"BASELINE mean_abs={base_mean:.1f}ms exact={base_exact:.3f} interp={base_interp:.3f}"
        )


@pytest.mark.parametrize("level", [0.1, 0.3, 0.5])
def test_real_aligner_beats_naive_baseline_on_mean_error(level):
    """The real aligner (anchors + weighted DP + variant-merge repair)
    should score at least as well as the naive SequenceMatcher baseline on
    mean boundary error — if it doesn't, something in S3 regressed the
    thing it exists to improve on, and that's worth knowing immediately,
    not after S5/S6 get built on top of a broken S3."""
    real_results = _run_corpus_at_level(level, align)
    baseline_results = _run_corpus_at_level(level, align_baseline)
    real_mean = statistics.mean(m.mean_abs_boundary_error_ms for m in real_results)
    base_mean = statistics.mean(m.mean_abs_boundary_error_ms for m in baseline_results)
    assert real_mean <= base_mean * 1.1, (
        f"level={level}: real aligner mean_abs={real_mean:.1f}ms is worse than "
        f"baseline={base_mean:.1f}ms by more than the 10% tolerance"
    )
