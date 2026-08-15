# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-15

### Added

- Alignment of a human-edited transcript to speech-to-text word timing, recovering a timestamp for every edited word and surviving small edits and whole sentences moved between positions (anchor chaining recovers relocated spans).
- VTT and SRT caption generation that respects the standard constraints (two lines, 42 characters per line, one to seven seconds, 21 characters per second) with no overlapping cues.
- QC: per-cue confidence statistics as JSON, caption constraint checks, and transposed-block flags for content the editor moved.
- STT adapters for faster-whisper (default), WhisperX and ElevenLabs, with a transcription cache keyed on audio content.
- Audio ingest via ffmpeg and transcript ingest from .docx and .txt.
- Command-line interface: single-file mode and batch mode (a directory of episodes -> per-file VTT/SRT/confidence JSON plus a qc_summary.csv).
- One-call pipeline API (`align_to_cues`) and a Streamlit demo.
- Double Metaphone phonetic matching behind an opt-in flag, off by default: measured as a regression on the synthetic benchmark corpus.
- Docker image with compose setup, and a MIT license.
- Committed sample output in `examples/`, produced by the real pipeline on the bundled sample pair.

[0.1.0]: https://github.com/PatricR73/Anchor-Align/releases/tag/v0.1.0
