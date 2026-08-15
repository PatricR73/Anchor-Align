"""S8 — SRT export, validated independently against webvtt-py's SRT reader."""

from __future__ import annotations

import webvtt

from anchor_align.export.srt import write_srt
from anchor_align.models import Cue

CUES = [
    Cue(index=1, start=1.0, end=4.0, lines=["Hello there."], word_span=(0, 2)),
    Cue(index=2, start=4.5, end=7.25, lines=["Second line one", "Second line two"], word_span=(2, 5)),
]


def test_write_srt_round_trips_through_webvtt_py(tmp_path):
    out = write_srt(CUES, tmp_path / "out.srt")
    parsed = webvtt.from_srt(str(out))
    assert len(parsed) == 2
    assert parsed[0].text == "Hello there."
    assert parsed[1].text == "Second line one\nSecond line two"


def test_write_srt_timestamps_use_comma_separator(tmp_path):
    out = write_srt(CUES, tmp_path / "out.srt")
    content = out.read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:04,000" in content
    assert "." not in content.split("-->")[0].split("\n")[-1]  # no dot in the timestamp itself


def test_write_srt_sequence_numbers_present(tmp_path):
    out = write_srt(CUES, tmp_path / "out.srt")
    content = out.read_text(encoding="utf-8")
    blocks = content.strip().split("\n\n")
    assert blocks[0].startswith("1\n")
    assert blocks[1].startswith("2\n")


def test_write_srt_returns_the_output_path(tmp_path):
    target = tmp_path / "out.srt"
    result = write_srt(CUES, target)
    assert result == target
