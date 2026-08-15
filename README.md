# anchor-align

Aligns a human-edited transcript to word-level timing produced by STT,
then segments it into VTT/SRT caption cues.

## The problem

Speech-to-text gives word-level timestamps for what was actually said; a
human editor's cleaned-up transcript (fillers removed, names fixed,
sentences reordered) is what should actually be captioned — but it no
longer lines up word-for-word with the STT output that carries the timing.
This project recovers, for every word in the edited transcript, the
timestamp it should have — robust to small text changes and to whole
sentences moving — then turns that into caption cues that satisfy
line/duration/reading-speed constraints without ever overlapping.

## Pipeline

| Stage | Module | What it does |
|---|---|---|
| S0 | `models.py`, `interfaces.py` | Data contracts (Pydantic v2, frozen) and the protocols the stages implement |
| S1 | `corrupt/` | Synthetic "human-edited transcript" generator with ground-truth mapping, for benchmarking; synthetic corpus with realistic pause structure |
| S2 | `normalize/` | 7-step normalization to a comparable form: span-invariant tokenizer, Unicode folding, punctuation-as-data, casefold/ASCII fold, phonetic keys, contractions, numeral expansion |
| S3 | `align/` | Anchor detection + displaced-block chaining, weighted Needleman-Wunsch, variant-merge repair, syllable-weighted interpolation, `align()` orchestrator, audio-order resolution |
| S4 | `benchmark/` | `difflib` baseline, `compute_metrics`, `compute_drift`, Polars aggregation + matplotlib plots via `run_benchmark` |
| S5 | `segment/` | Dynamic-programming cue segmentation over the caption constraints |
| S6 | `ingest/` | ffmpeg audio extraction, DOCX/TXT transcript parsing |
| S7 | `stt/` | faster-whisper adapter (default), optional WhisperX/ElevenLabs adapters, diskcache transcription cache |
| S8 | `export/` | VTT/SRT writers, QC report, per-cue confidence JSON |
| S9 | `demo/` | Streamlit app: upload, run the pipeline, review |
| — | `pipeline.py`, `cli.py` | One-call `align_to_cues()` and the `anchor-align` command-line entry point |

The caption limits (2 lines, 42 chars/line, 1-7s, 21 chars/s) live in
`caption_constraints.py` — the single source both segmentation and QC
enforce.

## Setup

With uv:

```bash
uv sync --all-extras --dev
uv run pytest
uv run ruff check .
uv run mypy src/anchor_align
```

Without uv (Python 3.11+):

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

Command line:

```bash
anchor-align podcast.mp3 transcript.docx --out captions/ --model base
```

Writes `captions.vtt`, `captions.srt` and `confidence.json` into the
output directory. `--language`, repeatable `--keyterm` hints, and
`--cache-dir` are available; run `anchor-align --help` for the full list.

As a library:

```python
from anchor_align.ingest.document import parse_transcript
from anchor_align.pipeline import align_to_cues
from anchor_align.stt.cache import cached_transcribe
from anchor_align.stt.faster_whisper_adapter import FasterWhisperAdapter

adapter = FasterWhisperAdapter(model_size="base")
transcription = cached_transcribe(audio_path, "faster-whisper-base", adapter, STTOptions())
result = align_to_cues(transcription.words, parse_transcript(transcript_path))
```

`result.cues` are the captions; `result.audio_order` is the words in true
audio order (the only order the export writers accept); `result.issues`
carries every QC finding.

Demo:

```bash
streamlit run demo/app.py
```

## Benchmark caveats

Every number in this repo's benchmark story comes from a synthetic
corruption model calibrated by feel, not from real (raw transcript,
published edited transcript) pairs. Two things remain unmeasured until
real data exists:

- **Gold timing noise.** STT timestamps carry their own error, worst
  precisely on disfluencies — the same things the `filler_removal` and
  `repetition_collapse` transforms target. Without a hand-labeled sample,
  no measured improvement has a known noise floor.
- **Real edit distribution.** Base rates in `CorruptionConfig` are tuned
  by feel. A held-out set of real edited transcripts is needed before any
  benchmark table can be read as a validated measurement.

Treat all S1-derived numbers as directional.

## Known limits of the aligner

- Chains shorter than 3 anchors are not recovered: a genuinely short or
  fragmented relocation falls through to pre-chaining behavior for that
  span, by construction.
- A leading/trailing orphan run with no anchor on either side collapses
  several words to one timestamp; those words are dropped from cue output
  and flagged `ZERO_DURATION_SPAN` rather than assigned a fake span.
- Exact 0.0ms recovery on relocated blocks is a property of this
  corruption model (S1 relocates text verbatim), not a general claim about
  reordering: when an editor rewrites a moved block's seams, 0.0 does not
  hold.

## Design decisions worth knowing before you change anything

- **Interpolation happens exactly once, at the point of production,
  bounded by its own segment's anchors.** There is no signal on an
  `AlignedWord` for "already resolved locally" vs. "still a raw
  placeholder", so a document-wide re-interpolation pass would silently
  overwrite segment-local resolution. Do not re-add one.
- **Captions are emitted in audio order, not document order — always.**
  A caption file's cue order *is* its timeline; a moved block is emitted
  at its true audio position and flagged `TRANSPOSED_BLOCK` (info
  severity, "needs human review") naming the edited-index range that
  moved. `segment_into_cues` and `qc_report` both raise on input that
  skips `resolve_audio_order`.
- **S1's corruption output is pinned.** `corrupt()` is deterministic per
  (master_seed, doc_id, level), draw-then-threshold sampling makes low
  levels strict subsets of high levels, and a golden test pins the exact
  output. Bump `GENERATOR_VERSION` in `corrupt/corruptor.py` on any
  transform-logic change, and regenerate the pinned hashes deliberately.

## Development

```bash
pytest                # full suite (includes the benchmark comparisons; several minutes)
pytest -k "not benchmark"  # quick pass over unit tests only
ruff check .
mypy src/anchor_align
```

Tests mirror the package layout under `tests/`; the benchmark tests print
the numbers that feed this README via `pytest -s`.
