"""S8 — VTT export, validated independently against webvtt-py (not just by
re-parsing our own writer, which could share a bug with the reader)."""

from __future__ import annotations

import webvtt

from anchor_align.export.vtt import write_vtt
from anchor_align.models import Cue

CUES = [
    Cue(index=1, start=1.0, end=4.0, lines=["Hello there."], word_span=(0, 2)),
    Cue(index=2, start=4.5, end=7.25, lines=["Second line one", "Second line two"], word_span=(2, 5)),
]


def test_write_vtt_round_trips_through_webvtt_py(tmp_path):
    out = write_vtt(CUES, tmp_path / "out.vtt")
    parsed = webvtt.read(str(out))
    assert len(parsed) == 2
    assert parsed[0].text == "Hello there."
    assert parsed[1].text == "Second line one\nSecond line two"


def test_write_vtt_timestamps_are_correct(tmp_path):
    out = write_vtt(CUES, tmp_path / "out.vtt")
    parsed = webvtt.read(str(out))
    assert parsed[0].start == "00:00:01.000"
    assert parsed[0].end == "00:00:04.000"
    assert parsed[1].start == "00:00:04.500"
    assert parsed[1].end == "00:00:07.250"


def test_write_vtt_starts_with_header(tmp_path):
    out = write_vtt(CUES, tmp_path / "out.vtt")
    assert out.read_text(encoding="utf-8").startswith("WEBVTT\n")


def test_write_vtt_empty_cues_still_valid(tmp_path):
    out = write_vtt([], tmp_path / "empty.vtt")
    parsed = webvtt.read(str(out))
    assert len(parsed) == 0


def test_write_vtt_returns_the_output_path(tmp_path):
    target = tmp_path / "out.vtt"
    result = write_vtt(CUES, target)
    assert result == target


def test_write_vtt_clamps_a_small_boundary_overlap(tmp_path):
    """A sub-frame overlap (e.g. two segments meeting exactly at a shared
    word boundary) is a formatting artifact, not a real timing conflict —
    the writer nudges it to the 40ms gap floor rather than leaving a
    negative/zero gap that visibly glitches in a player."""
    cues = [
        Cue(index=1, start=1.0, end=4.0, lines=["First."], word_span=(0, 1)),
        Cue(index=2, start=3.999, end=5.0, lines=["Second."], word_span=(1, 2)),
    ]
    out = write_vtt(cues, tmp_path / "clamped.vtt")
    parsed = webvtt.read(str(out))
    assert parsed[1].start == "00:00:04.040"
    # the original Cue objects passed in must not be mutated — qc_report
    # needs to see the real, unclamped timings
    assert cues[1].start == 3.999


def test_write_vtt_does_not_clamp_a_large_overlap(tmp_path):
    """A genuine overlap (real timing conflict, not a rounding artifact)
    must stay visible in the output rather than be silently papered over —
    export.qc.qc_report's OVERLAP check is what's supposed to surface it."""
    cues = [
        Cue(index=1, start=1.0, end=4.0, lines=["First."], word_span=(0, 1)),
        Cue(index=2, start=3.539, end=5.0, lines=["Second."], word_span=(1, 2)),
    ]
    out = write_vtt(cues, tmp_path / "unclamped.vtt")
    parsed = webvtt.read(str(out))
    assert parsed[1].start == "00:00:03.539"
