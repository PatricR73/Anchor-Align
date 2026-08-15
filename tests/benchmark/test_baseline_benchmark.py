"""S4 — baseline benchmark: align_baseline scored via compute_metrics
against the synthetic corpus (S1's generate_corpus), across corruption
levels. This is the first time a real timing-based metric exists in this
repo — every earlier baseline number (README, test_corruptor.py) was token
accuracy against S1's `mapping`, which can't distinguish a one-token slip
in fast speech from one across a two-second pause.

No real aligner (S3) exists yet, so this only benchmarks the baseline
against itself across levels — not baseline-vs-real. That's run_benchmark's
job once S3 lands.
"""

from __future__ import annotations

import statistics

from anchor_align.benchmark.adapters import to_edited_tokens
from anchor_align.benchmark.baseline import align_baseline
from anchor_align.benchmark.runner import compute_metrics
from anchor_align.corrupt.corpus import generate_corpus
from anchor_align.corrupt.corruptor import corrupt

CORPUS = generate_corpus(20, seed=1)


def _run_corpus_at_level(level: float, master_seed: int = 1):
    """Run the baseline over every corpus document at one level; returns
    the list of successfully-scored AlignmentMetrics (a doc where every
    token ended up INTERPOLATED or unmatched-to-gold is skipped — compute_metrics
    raises on that degenerate case by design, see its docstring)."""
    results = []
    for doc_id, gold_words in CORPUS:
        out = corrupt(gold_words, level=level, doc_id=doc_id, master_seed=master_seed)
        edited_tokens = to_edited_tokens(out.tokens)
        predicted = align_baseline(gold_words, edited_tokens)
        try:
            results.append(compute_metrics(predicted, gold_words, out.mapping))
        except ValueError:
            continue
    return results


def test_level_zero_has_near_zero_boundary_error():
    """Decisive sanity check, run first: at level=0.0 every edited token is
    an exact, untouched copy of gold, so align_baseline should match every
    token exactly and boundary error should be ~0 (allowing only for 1ms
    quantization noise)."""
    results = _run_corpus_at_level(0.0)
    assert results, "no documents were scorable at level=0.0 — something is broken upstream"
    for m in results:
        assert m.mean_abs_boundary_error_ms < 2.0
        assert m.p95_abs_boundary_error_ms < 2.0


def test_boundary_error_and_match_type_distribution_across_levels():
    """Report (not just assert) the time-weighted numbers this repo has
    been missing: mean/p95 boundary error in ms, and the match-type split,
    pooled across the corpus at each benchmarked level. Printed via -s so
    these are the numbers that go into README, not hand-copied from a
    one-off script."""
    summary = {}
    for level in (0.0, 0.1, 0.3, 0.5):
        results = _run_corpus_at_level(level)
        assert results, f"no documents were scorable at level={level}"
        mean_abs = statistics.mean(m.mean_abs_boundary_error_ms for m in results)
        mean_signed = statistics.mean(m.mean_signed_boundary_error_ms for m in results)
        mean_p95 = statistics.mean(m.p95_abs_boundary_error_ms for m in results)
        exact_frac = statistics.mean(m.match_type_distribution.get("exact", 0.0) for m in results)
        interp_frac = statistics.mean(m.match_type_distribution.get("interpolated", 0.0) for m in results)
        summary[level] = (mean_abs, mean_signed, mean_p95, exact_frac, interp_frac)
        print(
            f"level={level}: mean_abs={mean_abs:.1f}ms mean_signed={mean_signed:+.1f}ms "
            f"p95={mean_p95:.1f}ms exact={exact_frac:.3f} interpolated={interp_frac:.3f} "
            f"(n_docs={len(results)})"
        )

    # The one property this metric must have to be worth reporting: error
    # should not go DOWN as corruption increases (it's fine if it's noisy
    # or roughly flat at very low levels, since match_type distribution
    # dominates there, but a monotonic decrease would mean the metric is
    # measuring something other than what it claims to).
    assert summary[0.5][0] >= summary[0.0][0] - 5.0, "boundary error decreased sharply as corruption increased"
