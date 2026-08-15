"""S4 — run_benchmark's data pipeline: aggregation into two Polars tables
(benchmark_metrics.parquet, benchmark_drift.parquet). Plotting
(render_comparison_plots) is a separate module/test file — not covered
here.
"""

from __future__ import annotations

import polars as pl
import pytest

from anchor_align.benchmark.runner import (
    _BUCKET_ENUM,
    _MATCH_TYPE_COUNT_COLUMNS,
    _benchmark_row_to_flat_dict,
    _drift_row_to_flat_dict,
    _drift_rows_to_dataframe,
    _filter_by_bucket,
    _metrics_rows_to_dataframe,
    run_benchmark,
)
from anchor_align.models import (
    AlignedWord,
    AlignmentMetrics,
    BenchmarkRow,
    DriftBenchmarkRow,
    DriftMetrics,
    EditedToken,
    MatchType,
    ReorderTouch,
    TokenMapping,
)


def _edited_token(i: int = 0, text: str = "hi") -> EditedToken:
    return EditedToken(text=text, index=i, char_offset=0, sentence_id=0, is_sentence_end=False)


def _aligned_word(i: int = 0, start: float = 0.0, end: float = 1.0) -> AlignedWord:
    return AlignedWord(
        token=_edited_token(i), start=start, end=end, match_type=MatchType.EXACT, confidence=0.9
    )


def _mapping(edited_index: int, gold_indices: tuple[int, ...] = (0,), causes: frozenset[str] = frozenset()) -> TokenMapping:
    return TokenMapping(edited_index=edited_index, gold_indices=gold_indices, causes=causes)


# --------------------------------------------------------------------------
# _filter_by_bucket
# --------------------------------------------------------------------------


def test_filter_by_bucket_touched_keeps_only_reorder_tagged():
    predicted = [_aligned_word(0), _aligned_word(1), _aligned_word(2)]
    mapping = (
        _mapping(0, causes=frozenset({"sentence_reorder"})),
        _mapping(1, causes=frozenset()),
        _mapping(2, causes=frozenset({"sentence_reorder", "asr_name_correction"})),
    )
    filtered_predicted, filtered_mapping = _filter_by_bucket(predicted, mapping, ReorderTouch.TOUCHED)
    assert len(filtered_predicted) == 2
    assert len(filtered_mapping) == 2
    assert all("sentence_reorder" in m.causes for m in filtered_mapping)


def test_filter_by_bucket_not_touched_keeps_only_clean():
    predicted = [_aligned_word(0), _aligned_word(1), _aligned_word(2)]
    mapping = (
        _mapping(0, causes=frozenset({"sentence_reorder"})),
        _mapping(1, causes=frozenset()),
        _mapping(2, causes=frozenset({"filler_removal"})),
    )
    filtered_predicted, filtered_mapping = _filter_by_bucket(predicted, mapping, ReorderTouch.NOT_TOUCHED)
    assert len(filtered_predicted) == 2
    assert all("sentence_reorder" not in m.causes for m in filtered_mapping)


def test_filter_by_bucket_preserves_index_correspondence():
    predicted = [
        _aligned_word(0, start=10.0, end=11.0),
        _aligned_word(1, start=20.0, end=21.0),
        _aligned_word(2, start=30.0, end=31.0),
    ]
    mapping = (
        _mapping(0, causes=frozenset({"sentence_reorder"})),
        _mapping(1, causes=frozenset()),
        _mapping(2, causes=frozenset({"sentence_reorder"})),
    )
    filtered_predicted, filtered_mapping = _filter_by_bucket(predicted, mapping, ReorderTouch.TOUCHED)
    # predicted[0]<->mapping[0] and predicted[2]<->mapping[2] must stay paired
    assert [p.start for p in filtered_predicted] == [10.0, 30.0]
    assert [m.edited_index for m in filtered_mapping] == [0, 2]


def test_filter_by_bucket_empty_result_when_no_match():
    predicted = [_aligned_word(0)]
    mapping = (_mapping(0, causes=frozenset()),)
    filtered_predicted, filtered_mapping = _filter_by_bucket(predicted, mapping, ReorderTouch.TOUCHED)
    assert filtered_predicted == []
    assert filtered_mapping == ()


# --------------------------------------------------------------------------
# Row flattening
# --------------------------------------------------------------------------


def _sample_metrics() -> AlignmentMetrics:
    return AlignmentMetrics(
        mean_abs_boundary_error_ms=1.0,
        mean_signed_boundary_error_ms=0.5,
        p95_abs_boundary_error_ms=2.0,
        measured_word_count=5,
        match_type_counts={MatchType.ANCHOR: 3, MatchType.EXACT: 2},
    )


def _sample_drift() -> DriftMetrics:
    return DriftMetrics(
        body_mean_abs_error_ms=1.0,
        body_max_abs_error_ms=5.0,
        body_measured_count=10,
        tail_mean_abs_error_ms=2.0,
        tail_max_abs_error_ms=8.0,
        tail_measured_count=4,
    )


def test_benchmark_row_flattening_expands_match_type_counts_to_columns():
    row = BenchmarkRow(
        aligner_name="real", level=0.3, master_seed=1, config_hash="abc", doc_id="d1", metrics=_sample_metrics()
    )
    flat = _benchmark_row_to_flat_dict(row)
    assert flat["aligner_name"] == "real"
    assert flat["mean_abs_boundary_error_ms"] == 1.0
    assert flat["match_type_count_anchor"] == 3
    assert flat["match_type_count_exact"] == 2
    # every MatchType gets a column, even ones with a zero count
    assert flat["match_type_count_fuzzy"] == 0
    assert flat["match_type_count_phonetic"] == 0
    assert flat["match_type_count_interpolated"] == 0
    assert "metrics" not in flat
    assert "match_type_counts" not in flat


def test_drift_row_flattening_flattens_nested_drift_fields():
    row = DriftBenchmarkRow(
        aligner_name="baseline",
        level=0.1,
        master_seed=1,
        config_hash="xyz",
        doc_id="d2",
        bucket=ReorderTouch.NOT_TOUCHED,
        drift=_sample_drift(),
    )
    flat = _drift_row_to_flat_dict(row)
    assert flat["bucket"] == "not_touched_by_reorder"
    assert flat["body_mean_abs_error_ms"] == 1.0
    assert flat["tail_max_abs_error_ms"] == 8.0
    assert "drift" not in flat


# --------------------------------------------------------------------------
# DataFrame construction and dtype enforcement
# --------------------------------------------------------------------------


def test_metrics_rows_to_dataframe_has_one_row_per_input_row():
    rows = [
        BenchmarkRow(aligner_name="real", level=0.1, master_seed=1, config_hash="a", doc_id="d1", metrics=_sample_metrics()),
        BenchmarkRow(aligner_name="baseline", level=0.1, master_seed=1, config_hash="a", doc_id="d1", metrics=_sample_metrics()),
    ]
    df = _metrics_rows_to_dataframe(rows)
    assert df.shape[0] == 2
    assert set(df["aligner_name"].to_list()) == {"real", "baseline"}
    for col in _MATCH_TYPE_COUNT_COLUMNS:
        assert col in df.columns


def test_drift_rows_to_dataframe_bucket_column_is_polars_enum():
    rows = [
        DriftBenchmarkRow(
            aligner_name="real", level=0.1, master_seed=1, config_hash="a", doc_id="d1",
            bucket=ReorderTouch.TOUCHED, drift=_sample_drift(),
        ),
        DriftBenchmarkRow(
            aligner_name="real", level=0.1, master_seed=1, config_hash="a", doc_id="d1",
            bucket=ReorderTouch.NOT_TOUCHED, drift=_sample_drift(),
        ),
    ]
    df = _drift_rows_to_dataframe(rows)
    assert df.schema["bucket"] == _BUCKET_ENUM
    assert isinstance(df.schema["bucket"], pl.Enum)
    assert set(df.schema["bucket"].categories.to_list()) == {"touched_by_reorder", "not_touched_by_reorder"}


def test_drift_dataframe_rejects_a_third_bucket_value_at_the_type_level():
    # The whole point of pl.Enum over pl.Utf8/Categorical: a value outside
    # the fixed category set is a hard error, not silently accepted.
    df = pl.DataFrame({"bucket": ["touched_by_reorder", "not_touched_by_reorder"]})
    with pytest.raises(Exception):  # noqa: B017 - polars raises its own InvalidOperationError
        df.with_columns(pl.col("bucket").cast(pl.Enum(["touched_by_reorder", "not_touched_by_reorder"]))).vstack(
            pl.DataFrame({"bucket": ["bogus_third_bucket"]}).with_columns(
                pl.col("bucket").cast(pl.Enum(["touched_by_reorder", "not_touched_by_reorder", "bogus_third_bucket"]))
            )
        )


# --------------------------------------------------------------------------
# End-to-end
# --------------------------------------------------------------------------


def test_run_benchmark_end_to_end_writes_both_tables(tmp_path):
    output_dir = tmp_path / "results"
    returned = run_benchmark([0.1, 0.3], output_dir)

    assert returned == output_dir
    metrics_path = output_dir / "benchmark_metrics.parquet"
    drift_path = output_dir / "benchmark_drift.parquet"
    assert metrics_path.exists()
    assert drift_path.exists()

    metrics_df = pl.read_parquet(metrics_path)
    drift_df = pl.read_parquet(drift_path)

    assert metrics_df.shape[0] > 0
    assert drift_df.shape[0] > 0

    assert set(metrics_df["aligner_name"].unique().to_list()) == {"real", "baseline"}
    assert set(drift_df["aligner_name"].unique().to_list()) == {"real", "baseline"}
    assert set(metrics_df["level"].unique().to_list()) == {0.1, 0.3}
    assert set(drift_df["level"].unique().to_list()) == {0.1, 0.3}

    assert isinstance(drift_df.schema["bucket"], pl.Enum)
    assert set(drift_df.schema["bucket"].categories.to_list()) == {
        "touched_by_reorder",
        "not_touched_by_reorder",
    }
    assert set(drift_df["bucket"].unique().to_list()) <= {"touched_by_reorder", "not_touched_by_reorder"}

    # every row is traceable back to its exact corruption run
    for col in ("config_hash", "master_seed", "doc_id"):
        assert col in metrics_df.columns
        assert col in drift_df.columns
        assert metrics_df[col].null_count() == 0
        assert drift_df[col].null_count() == 0


def test_run_benchmark_also_renders_the_comparison_plots(tmp_path):
    """run_benchmark's own docstring promises it renders the plots, not
    just writes the tables — from the SAME DataFrames it just wrote, so
    the PNGs and the parquet files can never disagree with each other."""
    output_dir = tmp_path / "results"
    run_benchmark([0.1], output_dir)

    for name in ("mean_error_vs_level.png", "drift_not_touched.png", "drift_both_buckets.png"):
        path = output_dir / name
        assert path.exists(), f"{name} was not written by run_benchmark"
        assert path.stat().st_size > 0
