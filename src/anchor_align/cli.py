"""Command-line entry point: audio + edited transcript -> VTT/SRT/QC JSON.

Two modes:

- single file: `anchor-align audio.mp3 transcript.docx --out out/`
- batch: `anchor-align --batch in_dir --out out/` — every audio file is
  paired with a same-stem transcript (.txt/.docx) in the same directory;
  each pair produces captions.vtt/captions.srt/confidence.json named after
  the stem, plus a qc_summary.csv aggregating every file.
"""

from __future__ import annotations

import argparse
import csv
import logging
import statistics
import time
from pathlib import Path

from anchor_align.exceptions import AnchorAlignError
from anchor_align.export.qc import write_confidence_json
from anchor_align.export.srt import write_srt
from anchor_align.export.vtt import write_vtt
from anchor_align.ingest.document import parse_transcript
from anchor_align.logging_utils import configure_logging
from anchor_align.models import MatchType, STTOptions
from anchor_align.normalize.normalizer import DoubleMetaphoneEncoder
from anchor_align.pipeline import PipelineResult, align_to_cues
from anchor_align.stt.cache import DEFAULT_CACHE_DIR, cached_transcribe
from anchor_align.stt.faster_whisper_adapter import FasterWhisperAdapter

logger = logging.getLogger(__name__)

_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".mp4", ".flac", ".ogg"}
_TRANSCRIPT_EXTS = {".txt", ".docx"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anchor-align",
        description="Align a human-edited transcript to STT word timing and emit caption cues.",
    )
    parser.add_argument("audio", nargs="?", type=Path, help="audio or video file to transcribe")
    parser.add_argument("transcript", nargs="?", type=Path, help="edited transcript (.txt or .docx)")
    parser.add_argument("--batch", type=Path, metavar="DIR", help="process every audio/transcript pair in DIR")
    parser.add_argument("--out", type=Path, default=Path.cwd(), help="output directory (default: current directory)")
    parser.add_argument("--model", default="base", help="faster-whisper model size (default: base)")
    parser.add_argument("--language", default=None, help="language hint passed to the STT model")
    parser.add_argument("--keyterm", action="append", default=[], metavar="TERM", help="vocabulary hint; repeatable")
    parser.add_argument("--phonetic", action="store_true", help="enable Double Metaphone phonetic matching (opt-in by measurement)")
    parser.add_argument("--cache-dir", type=Path, default=None, help="transcription cache directory")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    return parser


def _pair_batch_files(in_dir: Path) -> list[tuple[Path, Path]]:
    """Pair each audio file with the single same-stem transcript; files
    with no transcript, or with several, are skipped and reported."""
    files = sorted(in_dir.iterdir())
    pairs: list[tuple[Path, Path]] = []
    for audio in files:
        if audio.suffix.lower() not in _AUDIO_EXTS:
            continue
        matches = [p for p in files if p.stem == audio.stem and p.suffix.lower() in _TRANSCRIPT_EXTS]
        if len(matches) == 1:
            pairs.append((audio, matches[0]))
        elif not matches:
            logger.warning("no transcript matching %s; skipping", audio.name)
        else:
            logger.warning("multiple transcripts match %s (%s); skipping", audio.name, [m.name for m in matches])
    return pairs


def _process_pair(
    audio: Path,
    transcript: Path,
    args: argparse.Namespace,
) -> PipelineResult:
    adapter = FasterWhisperAdapter(model_size=args.model)
    transcription = cached_transcribe(
        audio,
        f"faster-whisper-{args.model}",
        adapter,
        STTOptions(language=args.language, keyterms=args.keyterm),
        cache_dir=args.cache_dir or DEFAULT_CACHE_DIR,
    )
    edited_tokens = parse_transcript(transcript)
    return align_to_cues(
        transcription.words,
        edited_tokens,
        phonetic_encoder=DoubleMetaphoneEncoder() if args.phonetic else None,
    )


def _write_pair_outputs(result: PipelineResult, out_dir: Path, stem: str) -> None:
    write_vtt(result.cues, out_dir / f"{stem}.vtt")
    write_srt(result.cues, out_dir / f"{stem}.srt")
    write_confidence_json(result.cues, result.audio_order, out_dir / f"{stem}.confidence.json")


def _pair_stats(result: PipelineResult, elapsed_s: float) -> dict[str, object]:
    confidences = [w.confidence for w in result.audio_order]
    return {
        "cues": len(result.cues),
        "qc_errors": result.error_count,
        "qc_warnings": result.warning_count,
        "interpolated_words": sum(1 for w in result.audio_order if w.match_type == MatchType.INTERPOLATED),
        "mean_confidence": round(statistics.mean(confidences), 3) if confidences else None,
        "elapsed_s": round(elapsed_s, 2),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(logging.DEBUG if args.verbose else logging.INFO)

    if args.batch is not None:
        if not args.batch.is_dir():
            logger.error("batch directory not found: %s", args.batch)
            return 1
        pairs = _pair_batch_files(args.batch)
        if not pairs:
            logger.error("no audio/transcript pairs found in %s", args.batch)
            return 1
        args.out.mkdir(parents=True, exist_ok=True)
        summary: list[dict[str, object]] = []
        failures = 0
        for audio, transcript in pairs:
            start = time.perf_counter()
            try:
                result = _process_pair(audio, transcript, args)
            except AnchorAlignError as e:
                logger.error("%s: %s", audio.name, e)
                failures += 1
                continue
            _write_pair_outputs(result, args.out, audio.stem)
            elapsed = time.perf_counter() - start
            stats = _pair_stats(result, elapsed)
            summary.append({"file": audio.name, **stats})
            logger.info(
                "%s: %d cues, %d errors, %d warnings (%.1fs)",
                audio.name,
                stats["cues"],
                stats["qc_errors"],
                stats["qc_warnings"],
                elapsed,
            )
        with (args.out / "qc_summary.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary[0]) if summary else ["file"])
            writer.writeheader()
            writer.writerows(summary)
        logger.info("batch complete: %d/%d pairs processed, summary at %s", len(summary), len(pairs), args.out / "qc_summary.csv")
        return 1 if failures else 0

    if args.audio is None or args.transcript is None:
        build_parser().print_usage()
        logger.error("provide audio and transcript, or --batch DIR")
        return 2
    if not args.audio.is_file():
        logger.error("audio file not found: %s", args.audio)
        return 1
    if not args.transcript.is_file():
        logger.error("transcript file not found: %s", args.transcript)
        return 1

    try:
        result = _process_pair(args.audio, args.transcript, args)
    except AnchorAlignError as e:
        logger.error("%s", e)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    _write_pair_outputs(result, args.out, "captions")
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
