"""S4 — runs baseline vs. real aligner across every S1 corruption level,
aggregates with Polars, and renders the comparison plots with matplotlib.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Callable
from pathlib import Path

import numpy as np
import polars as pl

from anchor_align.align.aligner import align
from anchor_align.benchmark.adapters import to_edited_tokens
from anchor_align.benchmark.baseline import align_baseline
from anchor_align.benchmark.drift import compute_drift
from anchor_align.benchmark.plots import render_comparison_plots
from anchor_align.corrupt.corpus import generate_corpus, generate_long_document
from anchor_align.corrupt.corruptor import corrupt
from anchor_align.models import (
    AlignedWord,
    AlignmentMetrics,
    BenchmarkRow,
    DriftBenchmarkRow,
    EditedToken,
    MatchType,
    ReorderTouch,
    STTWord,
    TokenMapping,
)

logger = logging.getLogger(__name__)


def compute_metrics(
    predicted: list[AlignedWord],
    stt_words: list[STTWord],
    mapping: tuple[TokenMapping, ...],
) -> AlignmentMetrics:
    """Score one alignment run against S1 ground truth.

    `predicted[i]` is scored against `mapping[i]`'s TRUE gold indices (not
    against whatever `predicted[i].token` claims) — that's the whole point
    of having independent ground truth. A predicted word is only scored for
    boundary error if it's not INTERPOLATED (no real evidence to score) and
    its true `gold_indices` is non-empty (a true INSERTED token has no gold
    timing to compare against). True timing for a MERGE/SPLIT token is the
    [min(start), max(end)] envelope over every true gold index it covers.
    """
    if len(predicted) != len(mapping):
        raise ValueError(
            f"predicted has {len(predicted)} entries but mapping has {len(mapping)} — "
            "they must describe the same edited-token stream, 1:1"
        )

    match_type_counts: dict[MatchType, int] = dict.fromkeys(MatchType, 0)
    abs_errors_ms: list[float] = []
    signed_errors_ms: list[float] = []

    for pred, m in zip(predicted, mapping):
        match_type_counts[pred.match_type] += 1
        if pred.match_type == MatchType.INTERPOLATED or not m.gold_indices:
            continue
        true_start = min(stt_words[gi].start for gi in m.gold_indices)
        true_end = max(stt_words[gi].end for gi in m.gold_indices)
        signed_errors_ms.append((pred.start - true_start) * 1000)
        signed_errors_ms.append((pred.end - true_end) * 1000)
        abs_errors_ms.append(abs((pred.start - true_start) * 1000))
        abs_errors_ms.append(abs((pred.end - true_end) * 1000))

    if not abs_errors_ms:
        raise ValueError(
            "no scorable predictions: every token was either INTERPOLATED or had no true "
            "gold source — compute_metrics has nothing to measure for this run"
        )

    return AlignmentMetrics(
        mean_abs_boundary_error_ms=statistics.mean(abs_errors_ms),
        mean_signed_boundary_error_ms=statistics.mean(signed_errors_ms),
        p95_abs_boundary_error_ms=float(np.percentile(abs_errors_ms, 95, method="linear")),
        measured_word_count=len(abs_errors_ms) // 2,
        match_type_counts=match_type_counts,
    )


_AlignerFn = Callable[[list[STTWord], list[EditedToken]], list[AlignedWord]]
_ALIGNERS: tuple[tuple[str, _AlignerFn], ...] = (("real", align), ("baseline", align_baseline))

# generate_long_document's corpus for the drift comparison — separate from
# the whole-document comparison's corpus (generate_corpus), since a
# meaningful body/tail split needs a genuinely long document. Matches the
# methodology already used in tests/benchmark/test_long_file_drift_benchmark.py.
_N_LONG_DOCS = 8
_LONG_DOC_TARGET_WORDS = 4000
_MASTER_SEED = 1


def _build_benchmark_rows(corruption_levels: list[float]) -> list[BenchmarkRow]:
    """Whole-document AlignmentMetrics comparison: real aligner vs.
    baseline, over generate_corpus(20, seed=1), at every requested level.
    Skips (aligner, level, doc) combinations compute_metrics can't score
    (e.g. a document reduced to nothing but INTERPOLATED/INSERTED tokens)
    rather than crashing the whole run.
    """
    corpus = generate_corpus(20, seed=1)
    rows: list[BenchmarkRow] = []
    for aligner_name, aligner_fn in _ALIGNERS:
        for level in corruption_levels:
            for doc_id, gold_words in corpus:
                out = corrupt(gold_words, level=level, doc_id=doc_id, master_seed=_MASTER_SEED)
                edited_tokens = to_edited_tokens(out.tokens)
                predicted = aligner_fn(gold_words, edited_tokens)
                try:
                    metrics = compute_metrics(predicted, gold_words, out.mapping)
                except ValueError:
                    continue
                rows.append(
                    BenchmarkRow(
                        aligner_name=aligner_name,
                        level=level,
                        master_seed=_MASTER_SEED,
                        config_hash=out.manifest.config_hash,
                        doc_id=doc_id,
                        metrics=metrics,
                    )
                )
    return rows


def _filter_by_bucket(
    predicted: list[AlignedWord], mapping: tuple[TokenMapping, ...], bucket: ReorderTouch
) -> tuple[list[AlignedWord], tuple[TokenMapping, ...]]:
    """Filtered PARALLEL (predicted, mapping) lists restricted to tokens in
    `bucket` — TOUCHED iff "sentence_reorder" is in that token's true
    mapping.causes. Index correspondence between the two returned lists is
    preserved (same filter predicate applied in lockstep), which is what
    compute_drift's 1:1 zip(predicted, mapping) contract requires.
    """
    want_touched = bucket == ReorderTouch.TOUCHED
    filtered_predicted: list[AlignedWord] = []
    filtered_mapping: list[TokenMapping] = []
    for pred, m in zip(predicted, mapping):
        is_touched = "sentence_reorder" in m.causes
        if is_touched == want_touched:
            filtered_predicted.append(pred)
            filtered_mapping.append(m)
    return filtered_predicted, tuple(filtered_mapping)


def _build_drift_rows(corruption_levels: list[float]) -> list[DriftBenchmarkRow]:
    """Drift comparison, split by ReorderTouch bucket: real aligner vs.
    baseline, over `_N_LONG_DOCS` long synthetic documents, at every
    requested level. `gold_words` (the full document's STT words) is passed
    UNCHANGED to compute_drift for every bucket — the body/tail cutoff must
    be computed against the whole document's timeline, not a bucket
    subset's own truncated range; only `predicted`/`mapping` are filtered
    to the bucket. Skips combinations compute_drift can't score (no body or
    no tail sample in that bucket for that document) rather than crashing.
    """
    long_docs = [
        generate_long_document(seed=2000 + i, target_word_count=_LONG_DOC_TARGET_WORDS)
        for i in range(_N_LONG_DOCS)
    ]
    rows: list[DriftBenchmarkRow] = []
    for aligner_name, aligner_fn in _ALIGNERS:
        for level in corruption_levels:
            for doc_id, gold_words in long_docs:
                out = corrupt(gold_words, level=level, doc_id=doc_id, master_seed=_MASTER_SEED)
                edited_tokens = to_edited_tokens(out.tokens)
                predicted = aligner_fn(gold_words, edited_tokens)
                for bucket in ReorderTouch:
                    filtered_predicted, filtered_mapping = _filter_by_bucket(predicted, out.mapping, bucket)
                    try:
                        drift = compute_drift(filtered_predicted, gold_words, filtered_mapping)
                    except ValueError:
                        continue
                    rows.append(
                        DriftBenchmarkRow(
                            aligner_name=aligner_name,
                            level=level,
                            master_seed=_MASTER_SEED,
                            config_hash=out.manifest.config_hash,
                            doc_id=doc_id,
                            bucket=bucket,
                            drift=drift,
                        )
                    )
    return rows


_MATCH_TYPE_COUNT_COLUMNS = tuple(f"match_type_count_{mt.value}" for mt in MatchType)


def _benchmark_row_to_flat_dict(row: BenchmarkRow) -> dict[str, object]:
    """Flatten one BenchmarkRow (including its nested `metrics` and
    `metrics.match_type_counts`, which is keyed by the MatchType enum, not
    a plain string — Polars can't infer a struct dtype from enum-keyed dict
    values) into Polars-friendly scalar columns, one per MatchType.

    `.get(mt, 0)`, not `[mt]`: match_type_counts has no validator requiring
    every MatchType be present as a key — compute_metrics always populates
    all five via dict.fromkeys, but that's a property of that one caller.
    """
    dumped = row.model_dump()
    metrics = dumped.pop("metrics")
    match_type_counts = metrics.pop("match_type_counts")
    flat: dict[str, object] = {**dumped, **metrics}
    for mt in MatchType:
        flat[f"match_type_count_{mt.value}"] = match_type_counts.get(mt, 0)
    return flat


def _drift_row_to_flat_dict(row: DriftBenchmarkRow) -> dict[str, object]:
    """Flatten one DriftBenchmarkRow (including its nested `drift`).
    `bucket` stays a plain string here — cast to `pl.Enum` explicitly once
    the full DataFrame is built, since that's where the categories are
    enforced against the actual data."""
    dumped = row.model_dump()
    drift = dumped.pop("drift")
    return {**dumped, **drift}


_BUCKET_ENUM = pl.Enum([member.value for member in ReorderTouch])


def _metrics_rows_to_dataframe(rows: list[BenchmarkRow]) -> pl.DataFrame:
    return pl.DataFrame([_benchmark_row_to_flat_dict(row) for row in rows])


def _drift_rows_to_dataframe(rows: list[DriftBenchmarkRow]) -> pl.DataFrame:
    df = pl.DataFrame([_drift_row_to_flat_dict(row) for row in rows])
    return df.with_columns(pl.col("bucket").cast(_BUCKET_ENUM))


def run_benchmark(corruption_levels: list[float], output_dir: Path) -> Path:
    """Run baseline vs. real aligner at every corruption level, score each
    with compute_metrics/compute_drift, and write two Polars tables:

    - `benchmark_metrics.parquet`: one row per (aligner_name, level,
      master_seed, config_hash, doc_id) — whole-document AlignmentMetrics.
    - `benchmark_drift.parquet`: one row per (aligner_name, level,
      master_seed, config_hash, doc_id, bucket) — body/tail DriftMetrics
      split by ReorderTouch. `bucket` is a `pl.Enum` column with exactly
      ReorderTouch's two categories, not free text.

    Every row's config_hash/master_seed/doc_id trace it back to the exact
    corrupt() run it was measured against — a result becomes unusable the
    first time the config gets tuned if there's no way to tell whether a
    score moved because the aligner changed or the benchmark did.

    Also renders the comparison plots (benchmark/plots.py) from the SAME
    two DataFrames written above, so the parquet tables and the PNGs can
    never disagree. Returns `output_dir`.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_rows = _build_benchmark_rows(corruption_levels)
    metrics_df = _metrics_rows_to_dataframe(metrics_rows)
    metrics_df.write_parquet(output_dir / "benchmark_metrics.parquet")

    drift_rows = _build_drift_rows(corruption_levels)
    drift_df = _drift_rows_to_dataframe(drift_rows)
    drift_df.write_parquet(output_dir / "benchmark_drift.parquet")

    logger.info(
        "benchmark: %d metrics rows, %d drift rows at levels %s",
        len(metrics_rows),
        len(drift_rows),
        corruption_levels,
    )

    render_comparison_plots(metrics_df, drift_df, output_dir)

    return output_dir
