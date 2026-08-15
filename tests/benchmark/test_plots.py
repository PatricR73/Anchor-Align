"""S4 — render_comparison_plots: built and tested against hand-constructed
Polars DataFrames matching this module's own documented column contract
(src/anchor_align/benchmark/plots.py), independent of the aggregation
pipeline that will eventually produce these DataFrames for real.
"""

from __future__ import annotations

import polars as pl
import pytest

from anchor_align.benchmark.plots import (
    NOT_TOUCHED,
    TOUCHED,
    render_comparison_plots,
)

METRICS_SCHEMA = {
    "aligner_name": pl.Utf8,
    "level": pl.Float64,
    "doc_id": pl.Utf8,
    "mean_abs_boundary_error_ms": pl.Float64,
}

DRIFT_SCHEMA = {
    "aligner_name": pl.Utf8,
    "level": pl.Float64,
    "doc_id": pl.Utf8,
    "bucket": pl.Utf8,
    "body_mean_abs_error_ms": pl.Float64,
    "tail_mean_abs_error_ms": pl.Float64,
}


def _metrics_df(rows: list[tuple]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=METRICS_SCHEMA, orient="row")


def _drift_df(rows: list[tuple]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=DRIFT_SCHEMA, orient="row")


def _full_metrics_df() -> pl.DataFrame:
    return _metrics_df(
        [
            ("real", 0.1, "doc1", 2.4),
            ("real", 0.3, "doc1", 169.4),
            ("baseline", 0.1, "doc1", 2.8),
            ("baseline", 0.3, "doc1", 162.3),
            ("real", 0.1, "doc2", 3.0),
            ("baseline", 0.1, "doc2", 3.5),
        ]
    )


def _full_drift_df() -> pl.DataFrame:
    return _drift_df(
        [
            ("real", 0.1, "doc1", NOT_TOUCHED, 9.3, 4.2),
            ("real", 0.3, "doc1", NOT_TOUCHED, 7.7, 4.2),
            ("baseline", 0.1, "doc1", NOT_TOUCHED, 43.7, 22.1),
            ("baseline", 0.3, "doc1", NOT_TOUCHED, 120.5, 370.9),
            ("real", 0.1, "doc1", TOUCHED, 50.0, 6000.0),
            ("baseline", 0.1, "doc1", TOUCHED, 80.0, 8000.0),
        ]
    )


def test_returns_three_paths_that_exist_and_are_nonempty(tmp_path):
    paths = render_comparison_plots(_full_metrics_df(), _full_drift_df(), tmp_path)
    assert len(paths) == 3
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 0
        assert p.suffix == ".png"
        assert p.parent == tmp_path


def test_handles_empty_touched_bucket(tmp_path):
    drift_df = _full_drift_df().filter(pl.col("bucket") == NOT_TOUCHED)
    assert drift_df.filter(pl.col("bucket") == TOUCHED).height == 0
    paths = render_comparison_plots(_full_metrics_df(), drift_df, tmp_path)
    assert len(paths) == 3
    for p in paths:
        assert p.exists() and p.stat().st_size > 0


def test_handles_single_level(tmp_path):
    metrics_df = _metrics_df([("real", 0.1, "doc1", 2.4), ("baseline", 0.1, "doc1", 2.8)])
    drift_df = _drift_df(
        [
            ("real", 0.1, "doc1", NOT_TOUCHED, 9.3, 4.2),
            ("baseline", 0.1, "doc1", NOT_TOUCHED, 43.7, 22.1),
        ]
    )
    paths = render_comparison_plots(metrics_df, drift_df, tmp_path)
    assert len(paths) == 3
    for p in paths:
        assert p.exists() and p.stat().st_size > 0


def test_handles_completely_empty_drift_df(tmp_path):
    drift_df = _drift_df([])
    paths = render_comparison_plots(_full_metrics_df(), drift_df, tmp_path)
    assert len(paths) == 3
    for p in paths:
        assert p.exists() and p.stat().st_size > 0


def test_output_dir_created_if_missing(tmp_path):
    nested = tmp_path / "does" / "not" / "exist"
    assert not nested.exists()
    paths = render_comparison_plots(_full_metrics_df(), _full_drift_df(), nested)
    assert nested.exists()
    assert all(p.exists() for p in paths)


def test_bucket_accepts_polars_enum_dtype(tmp_path):
    """drift_df's bucket column may arrive as pl.Enum, not just pl.Utf8 —
    the module must accept either."""
    enum_dtype = pl.Enum([TOUCHED, NOT_TOUCHED])
    df = _full_drift_df().with_columns(pl.col("bucket").cast(enum_dtype))
    assert df.schema["bucket"] == enum_dtype
    paths = render_comparison_plots(_full_metrics_df(), df, tmp_path)
    assert len(paths) == 3
    for p in paths:
        assert p.exists() and p.stat().st_size > 0


def test_both_buckets_plot_bakes_independence_note_into_figure():
    """The bucket-independence caveat must be part of the saved figure
    itself (a fig.text() artist), not just a title or docstring — verified
    structurally since pixel comparison is not a reliable test signal: the
    note constant must be real, substantive prose, and the plotting
    function's source must reference it via fig.text (not merely define
    it and never use it)."""
    from anchor_align.benchmark.plots import _BUCKET_NOTE, _plot_drift_both_buckets

    assert "not statistically independent" in _BUCKET_NOTE.lower() or "not independent" in _BUCKET_NOTE.lower()
    assert len(_BUCKET_NOTE) > 50
    import inspect

    src = inspect.getsource(_plot_drift_both_buckets)
    assert "_BUCKET_NOTE" in src
    assert "fig.text" in src


def test_touched_bucket_visually_deemphasized_in_source():
    """The TOUCHED series must be rendered with reduced alpha and/or a
    hatch pattern relative to NOT_TOUCHED — checked structurally since
    pixel comparison is not a reliable test signal."""
    import inspect

    from anchor_align.benchmark.plots import _plot_drift_both_buckets

    src = inspect.getsource(_plot_drift_both_buckets)
    assert "hatch" in src
    assert "alpha" in src


@pytest.mark.parametrize("missing_col", ["aligner_name", "level", "mean_abs_boundary_error_ms"])
def test_missing_required_metrics_column_raises(tmp_path, missing_col):
    df = _full_metrics_df().drop(missing_col)
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        render_comparison_plots(df, _full_drift_df(), tmp_path)
