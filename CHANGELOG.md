# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Web app (React + FastAPI, under web/) replacing the Streamlit demo: upload audio and an edited transcript, run the full pipeline, and inspect the result — a confidence heatmap over the transcript with click-to-seek, a word-timeline scrubber with a live playhead, the cue list, the QC findings, and VTT/SRT/confidence-JSON downloads. The bundled sample runs with one click; FastAPI serves the built front end in production.
- Confidence is encoded twice in the web UI — color ramp plus a redundant solidity channel (font weight in the heatmap, bar height in the timeline). The color ramp alone sits on the red-green confusion axis and collapses under deuteranopia/protanopia and in grayscale; the second channel keeps low-confidence words readable without color. Rationale recorded in DESIGN.md so the channel is not reverted as visual noise.
- CI now exercises the web app on every push: a web job in .github/workflows/ci.yml rebuilds the 9,000-word fixture, starts the API and the Vite dev server, and runs the browser tools as failing gates — a11y/contrast/overflow audit, the P0 low-confidence-word seek check, the P1 timeline segment-width invariant, the playback scaling budget, and P6 payload / P7 bundle size budgets (web/ui/tools/payload-budget.mjs, bundle-budget.mjs, timeline-widths.mjs). The size-budget ceilings are stated in each tool with their measurements and headroom justification.
- fastapi, uvicorn, and python-multipart are now declared in pyproject.toml (and mirrored in requirements.txt) instead of only existing in the dev venv; CI installs with uv sync --frozen and the web tests import web.api, so an undeclared dependency would break the check job.

### Fixed

- Optional-adapter tests no longer fail when the extras are installed: the whisperx/elevenlabs "package missing" tests skip when the package is importable, because CI syncs --all-extras which installs both.

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
