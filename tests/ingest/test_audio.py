"""S6 — audio ingest via ffmpeg. Uses ffmpeg's lavfi synthetic sources
(sine wave / silence) so tests don't need a checked-in media fixture."""

from __future__ import annotations

import subprocess
import wave

import pytest

from anchor_align.exceptions import IngestError
from anchor_align.ingest.audio import extract_audio


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")


def _make_source_video(path, duration=1.0):
    """A tiny synthetic video+audio file via ffmpeg's lavfi sources — no
    checked-in binary fixture needed."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size=64x64:rate=5",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


def test_extract_audio_produces_16khz_mono_wav(tmp_path):
    src = tmp_path / "source.mp4"
    _make_source_video(src)
    out_path = tmp_path / "out.wav"

    result = extract_audio(src, out_path)

    assert result == out_path
    assert out_path.exists()
    with wave.open(str(out_path), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2  # pcm_s16le


def test_extract_audio_creates_parent_directories(tmp_path):
    src = tmp_path / "source.mp4"
    _make_source_video(src)
    out_path = tmp_path / "nested" / "dir" / "out.wav"

    extract_audio(src, out_path)

    assert out_path.exists()


def test_extract_audio_raises_on_ffmpeg_failure(tmp_path):
    missing = tmp_path / "does_not_exist.mp4"
    out_path = tmp_path / "out.wav"
    with pytest.raises(IngestError, match="ffmpeg failed"):
        extract_audio(missing, out_path)
