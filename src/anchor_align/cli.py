"""Command-line entry point: audio + edited transcript -> VTT/SRT/QC JSON.

Runs the full pipeline (transcribe via faster-whisper, align, segment,
QC) and writes captions.vtt, captions.srt and confidence.json into the
output directory.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from anchor_align.exceptions import AnchorAlignError
from anchor_align.export.qc import write_confidence_json
from anchor_align.export.srt import write_srt
from anchor_align.export.vtt import write_vtt
from anchor_align.ingest.document import parse_transcript
from anchor_align.logging_utils import configure_logging
from anchor_align.models import STTOptions
from anchor_align.pipeline import align_to_cues
from anchor_align.stt.cache import DEFAULT_CACHE_DIR, cached_transcribe
from anchor_align.stt.faster_whisper_adapter import FasterWhisperAdapter

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anchor-align",
        description="Align a human-edited transcript to STT word timing and emit caption cues.",
    )
    parser.add_argument("audio", type=Path, help="audio or video file to transcribe")
    parser.add_argument("transcript", type=Path, help="edited transcript (.txt or .docx)")
    parser.add_argument("--out", type=Path, default=Path.cwd(), help="output directory (default: current directory)")
    parser.add_argument("--model", default="base", help="faster-whisper model size (default: base)")
    parser.add_argument("--language", default=None, help="language hint passed to the STT model")
    parser.add_argument("--keyterm", action="append", default=[], metavar="TERM", help="vocabulary hint; repeatable")
    parser.add_argument("--cache-dir", type=Path, default=None, help="transcription cache directory")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(logging.DEBUG if args.verbose else logging.INFO)

    if not args.audio.is_file():
        logger.error("audio file not found: %s", args.audio)
        return 1
    if not args.transcript.is_file():
        logger.error("transcript file not found: %s", args.transcript)
        return 1

    try:
        adapter = FasterWhisperAdapter(model_size=args.model)
        transcription = cached_transcribe(
            args.audio,
            f"faster-whisper-{args.model}",
            adapter,
            STTOptions(language=args.language, keyterms=args.keyterm),
            cache_dir=args.cache_dir or DEFAULT_CACHE_DIR,
        )
        edited_tokens = parse_transcript(args.transcript)
        result = align_to_cues(transcription.words, edited_tokens)
    except AnchorAlignError as e:
        logger.error("%s", e)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    write_vtt(result.cues, args.out / "captions.vtt")
    write_srt(result.cues, args.out / "captions.srt")
    write_confidence_json(result.cues, result.audio_order, args.out / "confidence.json")

    logger.info(
        "wrote %d cues to %s (errors=%d, warnings=%d)",
        len(result.cues),
        args.out,
        result.error_count,
        result.warning_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
