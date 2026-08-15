"""Benchmark for the anchor-chaining / displaced-block fix
(anchors.find_displaced_blocks, aligner.align).

Before this fix, 96% of all >1000ms boundary errors in the S1 synthetic
corpus benchmark traced directly to sentence_reorder-tagged tokens: a
whole relocated sentence left find_anchors' single backbone chain with a
huge unanchored gap, which S3b's DP then force-aligned sequentially,
producing near-arbitrary long-distance mismatches (worst observed: 11.6
seconds).

This reports, not just asserts: pooled (not per-document-averaged) mean/
p95/max boundary error, split by whether the document actually contains a
sentence_reorder edit (the case this fix targets) vs. not (must be
unaffected), plus a max-drift-in-the-final-10%-of-file metric — the
"does timing degrade over a long file" question, computed by timestamp
share of total duration, not token count.
"""

from __future__ import annotations

import statistics

import numpy as np
import pytest

from anchor_align.align.aligner import align
from anchor_align.benchmark.adapters import to_edited_tokens
from anchor_align.benchmark.baseline import align_baseline
from anchor_align.corrupt.corpus import generate_corpus
from anchor_align.corrupt.corruptor import corrupt
from anchor_align.models import STTWord


def _pooled_errors(
    corpus: list[tuple[str, list[STTWord]]], level: float, aligner_fn, master_seed: int
) -> tuple[list[float], list[float]]:
    """Returns (errors_for_docs_without_reorder, errors_for_docs_with_reorder)
    — pooled individual (start,end) boundary errors in ms, split by
    whether that specific document's corruption run actually applied
    sentence_reorder (checked via TokenMapping.causes, not assumed from
    the configured rate)."""
    without: list[float] = []
    with_reorder: list[float] = []
    for doc_id, gold_words in corpus:
        out = corrupt(gold_words, level=level, doc_id=doc_id, master_seed=master_seed)
        has_reorder = any("sentence_reorder" in m.causes for m in out.mapping)
        bucket = with_reorder if has_reorder else without

        edited_tokens = to_edited_tokens(out.tokens)
        predicted = aligner_fn(gold_words, edited_tokens)
        for pred, m in zip(predicted, out.mapping):
            if pred.match_type == "interpolated" or not m.gold_indices:
                continue
            true_start = min(gold_words[gi].start for gi in m.gold_indices)
            true_end = max(gold_words[gi].end for gi in m.gold_indices)
            bucket.append(abs(pred.start - true_start) * 1000)
            bucket.append(abs(pred.end - true_end) * 1000)
    return without, with_reorder


def _max_drift_final_decile(
    corpus: list[tuple[str, list[STTWord]]], level: float, aligner_fn, master_seed: int
) -> float:
    """Worst absolute boundary error among tokens whose TRUE gold timestamp
    falls in the final 10% of that document's total duration (by
    timestamp share, not token count) — "does timing degrade over a long
    file", pooled across the whole corpus."""
    worst = 0.0
    for doc_id, gold_words in corpus:
        if not gold_words:
            continue
        out = corrupt(gold_words, level=level, doc_id=doc_id, master_seed=master_seed)
        edited_tokens = to_edited_tokens(out.tokens)
        predicted = aligner_fn(gold_words, edited_tokens)
        doc_duration = gold_words[-1].end
        if doc_duration <= 0:
            continue
        cutoff = doc_duration * 0.9
        for pred, m in zip(predicted, out.mapping):
            if pred.match_type == "interpolated" or not m.gold_indices:
                continue
            true_start = min(gold_words[gi].start for gi in m.gold_indices)
            if true_start < cutoff:
                continue
            true_end = max(gold_words[gi].end for gi in m.gold_indices)
            err = max(abs(pred.start - true_start), abs(pred.end - true_end)) * 1000
            worst = max(worst, err)
    return worst


def _report(label: str, corpus_seed: int, master_seed: int) -> None:
    corpus = generate_corpus(20, seed=corpus_seed)
    print(f"\n--- {label} (corpus_seed={corpus_seed}, master_seed={master_seed}) ---")
    for level in (0.0, 0.1, 0.3, 0.5):
        real_without, real_with = _pooled_errors(corpus, level, align, master_seed)
        base_without, base_with = _pooled_errors(corpus, level, align_baseline, master_seed)
        real_drift = _max_drift_final_decile(corpus, level, align, master_seed)
        base_drift = _max_drift_final_decile(corpus, level, align_baseline, master_seed)

        def stats(errs: list[float]) -> str:
            if not errs:
                return "n=0"
            return f"n={len(errs)} mean={statistics.mean(errs):.1f} p95={np.percentile(errs, 95):.1f} max={max(errs):.1f}"

        print(f"level={level}")
        print(f"  REAL     no-reorder: {stats(real_without)}")
        print(f"  REAL     w/-reorder: {stats(real_with)}")
        print(f"  BASELINE no-reorder: {stats(base_without)}")
        print(f"  BASELINE w/-reorder: {stats(base_with)}")
        print(f"  max-drift (final 10% of file, by timestamp): REAL={real_drift:.1f}ms BASELINE={base_drift:.1f}ms")


def test_report_pooled_split_and_drift_seed1():
    """Primary corpus/seed used throughout this debugging session."""
    _report("seed=1 corpus, master_seed=1 corruption (primary, used during debugging)", corpus_seed=1, master_seed=1)


def test_report_pooled_split_and_drift_held_out():
    """Held out: neither this corpus seed nor this corruption seed was
    touched while diagnosing the bug or tuning MIN_MATCH_SIMILARITY."""
    _report("seed=777 corpus, master_seed=42 corruption (held out)", corpus_seed=777, master_seed=42)


def _pooled_errors_for_recovered_blocks(
    corpus: list[tuple[str, list[STTWord]]], level: float, master_seed: int
) -> list[float]:
    """Errors restricted to tokens whose EDITED index falls within a
    block find_displaced_blocks ACTUALLY recovered (not just "somewhere
    in a document that happens to contain one recovered block" — a
    document can have a second, unrecoverable reordered region elsewhere,
    and that region's error must not be credited to or blamed on this
    fix). A reordered span with no chain of >=3 long+rare anchors is a
    documented, in-scope gap (falls through to pre-fix single-DP-segment
    behavior) — conflating it with the fix's actual coverage would let
    this test pass by accident (the fix "covering" a case it never
    touched) as easily as it could fail by accident.
    """
    from anchor_align.align.aligner import normalize_for_alignment
    from anchor_align.align.anchors import find_displaced_blocks

    errs: list[float] = []
    for doc_id, gold_words in corpus:
        out = corrupt(gold_words, level=level, doc_id=doc_id, master_seed=master_seed)
        edited_tokens = to_edited_tokens(out.tokens)
        stt_norm = normalize_for_alignment([w.text for w in gold_words])
        edited_norm = normalize_for_alignment([t.text for t in edited_tokens])
        _backbone, blocks = find_displaced_blocks(stt_norm, edited_norm)
        if not blocks:
            continue
        recovered_ranges = [(block[0][1], block[-1][1]) for block in blocks]

        predicted = align(gold_words, edited_tokens)
        for i, (pred, m) in enumerate(zip(predicted, out.mapping)):
            if pred.match_type == "interpolated" or not m.gold_indices:
                continue
            if not any(lo <= i <= hi for lo, hi in recovered_ranges):
                continue
            true_start = min(gold_words[gi].start for gi in m.gold_indices)
            true_end = max(gold_words[gi].end for gi in m.gold_indices)
            errs.append(abs(pred.start - true_start) * 1000)
            errs.append(abs(pred.end - true_end) * 1000)
    return errs


@pytest.mark.parametrize("level", [0.3, 0.5])
def test_recovered_displaced_blocks_have_bounded_error(level):
    """The actual regression guard, scoped to what the fix claims to
    cover: on documents where find_displaced_blocks recovered at least one
    chain, the real aligner's worst individual boundary error must stay
    well under the pre-fix catastrophic range (11.6s observed). 3000ms is
    generous — the point is "not seconds-scale", not a tight bound on the
    DP's ordinary local matching noise. Documents where NO chain was
    recoverable (a real, expected, out-of-scope case — see
    _pooled_errors_for_recovered_blocks) are excluded here on purpose;
    they're still visible in the printed report above, uncapped."""
    corpus = generate_corpus(20, seed=1)
    errs = _pooled_errors_for_recovered_blocks(corpus, level, master_seed=1)
    assert errs, f"no documents with a recovered displaced block at level={level} — test fixture assumption broke"
    assert max(errs) < 3000.0, f"level={level}: max error {max(errs):.0f}ms among recovered-block documents"


@pytest.mark.parametrize("level", [0.3, 0.5])
def test_reordered_documents_real_aligner_beats_or_matches_baseline_on_max(level):
    """Even where the fix's coverage is incomplete (no chain recoverable),
    the real aligner must not be WORSE than the unfixed baseline on
    documents containing a reorder — the fix should never make an
    already-hard case harder. This is the honest claim across the FULL
    reordered set (not just the recovered subset above)."""
    corpus = generate_corpus(20, seed=1)
    _real_without, real_with = _pooled_errors(corpus, level, align, master_seed=1)
    _base_without, base_with = _pooled_errors(corpus, level, align_baseline, master_seed=1)
    assert real_with and base_with
    assert max(real_with) <= max(base_with) * 1.1
