"""S6 — audio ingest: ffmpeg via subprocess, video.mp4 -> 16kHz mono WAV."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from anchor_align.exceptions import IngestError

logger = logging.getLogger(__name__)


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """Run ffmpeg -i video_path -ar 16000 -ac 1 -c:a pcm_s16le output_path.

    16kHz mono PCM16 is faster-whisper's/WhisperX's native input rate —
    no reason to hand them anything higher and make them resample
    internally. `-y` overwrites `output_path` unconditionally: this
    function's contract is "produce output_path", not "refuse if it
    exists".
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,  # returncode checked explicitly below for a custom error message
    )
    if result.returncode != 0:
        raise IngestError(f"ffmpeg failed (exit {result.returncode}) on {video_path}:\n{result.stderr}")
    logger.info("extracted 16kHz mono wav %s <- %s", output_path, video_path)
    return output_path
