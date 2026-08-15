"""S4 — matplotlib comparison plots for the S4-final benchmark (real
aligner vs. baseline), consuming the flat Polars tables `run_benchmark`
writes.

Kept separate from runner.py's aggregation logic on purpose: this module
only renders what it's handed, so it can be built and tested against
hand-constructed DataFrames without depending on the aggregation pipeline,
and reviewed/changed independently of it.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: this module never opens a display
import matplotlib.pyplot as plt
import polars as pl

# --------------------------------------------------------------------------
# Expected column contracts
#
# metrics_df — one row per (aligner_name, level, doc_id), flattening
# BenchmarkRow (models.py) with `.metrics` unnested:
#   aligner_name: str, level: f64, doc_id: str
#   mean_abs_boundary_error_ms: f64
#
# drift_df — one row per (aligner_name, level, doc_id, bucket), flattening
# DriftBenchmarkRow with `.drift` unnested:
#   aligner_name: str, level: f64, doc_id: str
#   bucket: str, one of ReorderTouch's two values (Enum or plain Utf8)
#   body_mean_abs_error_ms: f64, tail_mean_abs_error_ms: f64
#
# Extra columns (master_seed, config_hash, p95, max, counts, ...) are
# ignored here — this module only reads what it plots.
# --------------------------------------------------------------------------

TOUCHED = "touched_by_reorder"
NOT_TOUCHED = "not_touched_by_reorder"

_BUCKET_NOTE = (
    "Bucket = whether THIS token was itself touched by a reorder edit,\n"
    "not whether the whole document is otherwise clean. Drift propagates\n"
    "downstream of where it originates, so 'not touched' timing can still\n"
    "inherit error from a 'touched' span earlier in the same document —\n"
    "the two buckets are NOT statistically independent samples."
)


def _bucket_str(col: pl.Expr) -> pl.Expr:
    """Accept bucket as pl.Enum or plain pl.Utf8 — cast defensively so this
    module doesn't hard-fail on a reasonable dtype choice from whichever
    pipeline built drift_df."""
    return col.cast(pl.Utf8)


def render_comparison_plots(metrics_df: pl.DataFrame, drift_df: pl.DataFrame, output_dir: Path) -> list[Path]:
    """Render the S4-final comparison plots to `output_dir` as PNGs.
    Returns the list of written paths. Empty input for a given plot's slice
    (e.g. no TOUCHED rows) is handled by skipping that series, not by
    raising — a benchmark run with one empty bucket is still a valid run to
    report on.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    paths.append(_plot_mean_error_vs_level(metrics_df, output_dir))
    paths.append(_plot_drift_not_touched(drift_df, output_dir))
    paths.append(_plot_drift_both_buckets(drift_df, output_dir))

    return paths


def _plot_mean_error_vs_level(metrics_df: pl.DataFrame, output_dir: Path) -> Path:
    """Mean boundary error vs. corruption level, one line per aligner —
    expected to show the two lines close together, NOT a clear win for
    either side: both methods compute a monotone alignment path and fail on
    the same block-move input the same way. That's the point being
    illustrated."""
    fig, ax = plt.subplots(figsize=(7, 5))

    agg = (
        metrics_df.group_by(["aligner_name", "level"])
        .agg(pl.col("mean_abs_boundary_error_ms").mean().alias("mean_ms"))
        .sort(["aligner_name", "level"])
    )

    for aligner_name in agg["aligner_name"].unique(maintain_order=True).sort():
        sub = agg.filter(pl.col("aligner_name") == aligner_name)
        ax.plot(sub["level"], sub["mean_ms"], marker="o", label=aligner_name)

    ax.set_xlabel("corruption level")
    ax.set_ylabel("mean absolute boundary error (ms)")
    ax.set_title("Mean boundary error vs. corruption level\n(near parity is expected — see body-vs-tail drift plot for the real divergence)")
    if ax.get_legend_handles_labels()[0]:
        ax.legend()
    fig.tight_layout()

    path = output_dir / "mean_error_vs_level.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_drift_not_touched(drift_df: pl.DataFrame, output_dir: Path) -> Path:
    """Body vs. tail error, real vs. baseline, per level — restricted to
    NOT_TOUCHED tokens only. This is the primary, trustworthy "does
    anchoring bound drift" comparison: periodic re-anchoring should keep
    tail error from running away from body error; a purely sequential
    matcher has no way to re-establish position partway through a file and
    should show tail > body, increasingly so as corruption rises.
    """
    fig, ax = plt.subplots(figsize=(8, 5))

    sub = drift_df.filter(_bucket_str(pl.col("bucket")) == NOT_TOUCHED)
    if sub.height == 0:
        ax.text(0.5, 0.5, "no NOT_TOUCHED rows in drift_df", ha="center", va="center", transform=ax.transAxes)
    else:
        agg = (
            sub.group_by(["aligner_name", "level"])
            .agg(
                pl.col("body_mean_abs_error_ms").mean().alias("body_ms"),
                pl.col("tail_mean_abs_error_ms").mean().alias("tail_ms"),
            )
            .sort(["aligner_name", "level"])
        )
        aligners = agg["aligner_name"].unique(maintain_order=True).sort().to_list()
        levels = sorted(agg["level"].unique().to_list())
        x = list(range(len(levels)))
        width = 0.8 / max(len(aligners) * 2, 1)

        for a_idx, aligner_name in enumerate(aligners):
            a_sub = agg.filter(pl.col("aligner_name") == aligner_name).sort("level")
            by_level = dict(zip(a_sub["level"].to_list(), zip(a_sub["body_ms"].to_list(), a_sub["tail_ms"].to_list())))
            offset_body = (a_idx * 2) * width - 0.4
            offset_tail = (a_idx * 2 + 1) * width - 0.4
            # Skip levels this aligner has no row for — a missing value
            # must be an absent bar, not a bar of height None.
            body_x = [x[i] + offset_body for i, lv in enumerate(levels) if lv in by_level]
            body_y = [by_level[lv][0] for lv in levels if lv in by_level]
            tail_x = [x[i] + offset_tail for i, lv in enumerate(levels) if lv in by_level]
            tail_y = [by_level[lv][1] for lv in levels if lv in by_level]
            if body_x:
                ax.bar(body_x, body_y, width, label=f"{aligner_name} body")
            if tail_x:
                ax.bar(tail_x, tail_y, width, label=f"{aligner_name} tail")

        ax.set_xticks(x)
        ax.set_xticklabels([str(lv) for lv in levels])

    ax.set_xlabel("corruption level")
    ax.set_ylabel("mean absolute boundary error (ms)")
    ax.set_title("Drift: body vs. tail error (NOT_TOUCHED tokens only)")
    if ax.get_legend_handles_labels()[0]:
        ax.legend()
    fig.text(0.5, 0.01, _BUCKET_NOTE, ha="center", va="bottom", fontsize=7, wrap=True)
    fig.tight_layout(rect=(0, 0.14, 1, 1))

    path = output_dir / "drift_not_touched.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_drift_both_buckets(drift_df: pl.DataFrame, output_dir: Path) -> Path:
    """Both buckets shown for context. The TOUCHED bucket is visually
    de-emphasized (hatched, reduced alpha) relative to NOT_TOUCHED so it
    does not read as a parallel, independent category — and a note baked
    directly into the saved figure states explicitly that the two buckets
    are not statistically independent.
    """
    fig, ax = plt.subplots(figsize=(9, 5))

    if drift_df.height == 0:
        ax.text(0.5, 0.5, "no rows in drift_df", ha="center", va="center", transform=ax.transAxes)
    else:
        agg = (
            drift_df.with_columns(_bucket_str(pl.col("bucket")).alias("bucket_str"))
            .group_by(["aligner_name", "level", "bucket_str"])
            .agg(
                pl.col("body_mean_abs_error_ms").mean().alias("body_ms"),
                pl.col("tail_mean_abs_error_ms").mean().alias("tail_ms"),
            )
            .sort(["aligner_name", "level", "bucket_str"])
        )
        aligners = agg["aligner_name"].unique(maintain_order=True).sort().to_list()
        levels = sorted(agg["level"].unique().to_list())
        x = list(range(len(levels)))
        series = [(a, b) for a in aligners for b in (NOT_TOUCHED, TOUCHED)]
        width = 0.85 / max(len(series), 1)

        for idx, (aligner_name, bucket) in enumerate(series):
            b_sub = agg.filter((pl.col("aligner_name") == aligner_name) & (pl.col("bucket_str") == bucket))
            by_level = dict(zip(b_sub["level"].to_list(), b_sub["tail_ms"].to_list()))
            offset = idx * width - 0.42
            # Skip levels/buckets with no row rather than plotting a bar of
            # height None.
            bar_x = [x[i] + offset for i, lv in enumerate(levels) if lv in by_level]
            bar_y = [by_level[lv] for lv in levels if lv in by_level]
            if not bar_x:
                continue
            is_touched = bucket == TOUCHED
            ax.bar(
                bar_x,
                bar_y,
                width,
                label=f"{aligner_name} tail ({bucket})",
                alpha=0.4 if is_touched else 1.0,
                hatch="//" if is_touched else None,
                edgecolor="black" if is_touched else None,
            )

        ax.set_xticks(x)
        ax.set_xticklabels([str(lv) for lv in levels])

    ax.set_xlabel("corruption level")
    ax.set_ylabel("mean absolute tail boundary error (ms)")
    ax.set_title("Both buckets (tail error) — TOUCHED shown hatched/faded: not an independent comparison")
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8)
    fig.text(0.5, 0.01, _BUCKET_NOTE, ha="center", va="bottom", fontsize=7, wrap=True)
    fig.tight_layout(rect=(0, 0.16, 1, 1))

    path = output_dir / "drift_both_buckets.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
