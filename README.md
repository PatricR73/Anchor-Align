# anchor-align

[![CI](https://github.com/PatricR73/Anchor-Align/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/PatricR73/Anchor-Align/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

Takes a transcript that an editor cleaned up and the word timings from speech-to-text, and produces VTT caption cues.

Built for localization vendors, podcast networks, e-learning teams and broadcasters who publish human-edited transcripts and need compliant captions generated from them.

The European Accessibility Act has been enforceable since June 2025 and creates a captioning obligation for media and e-learning sold into the EU.

## Results at a glance

| Measurement | anchor-align | difflib baseline |
|---|---|---|
| Tail mean abs boundary error, level 0.3, untouched tokens | 4.0 ms | 370.9 ms |
| Tail mean abs boundary error, level 0.1, untouched tokens | 4.2 ms | 22.1 ms |
| Mean abs boundary error, level 0.3 | 155.9 ms | 162.3 ms |
| Worst-case boundary error on documents containing a reorder, level 0.5 | 6708 ms | 20540 ms |

The benchmark corpus is synthetic and there is no validation on real transcripts yet; see BENCHMARKS.md for the full caveats.

![Demo](docs/demo.gif)

## The problem this solves

Speech-to-text gives you timestamps for every word that was said. Then a human editor fixes the transcript: drops the "um"s, corrects the names, moves a sentence to a better place. The edited text reads properly now, but it no longer matches the STT output word for word, and the STT output is the only thing carrying timing. So you have a good transcript with no timing, and a timed transcript nobody wants to caption.

This project bridges that. It recovers, for every word in the edited transcript, the timestamp it should have, and it's designed to survive both small text changes and whole sentences being moved around. The cues it produces obey the usual caption constraints (two lines max, 42 characters per line, one to seven seconds, 21 characters per second) and never overlap.

## Install

Python 3.11 or newer.

```bash
pip install -e ".[dev]"
```

## Use

A single file:

```bash
anchor-align podcast.mp3 transcript.docx --out captions/
```

A whole directory of episodes:

```bash
anchor-align --batch episodes/ --out captions/
```

Batch mode pairs each audio file with a same-named .txt or .docx, processes every pair, and writes qc_summary.csv with the per-file counts at the end.

Output is captions.vtt, captions.srt and captions.confidence.json per file. The confidence JSON gives per-cue mean and min confidence, so you can spot weak stretches without opening the video.

The bundled sample in [examples/](examples/) shows what this produces for the shipped `data/sample/` pair: `sample_output.vtt`, `sample_output.srt` and `sample_output.confidence.json`, with the exact command and a walk-through of one cue in [examples/README.md](examples/README.md).

Flags worth knowing:

- `--model` — faster-whisper size, `base` by default. `small` or `medium` if you need better accuracy and have the patience.
- `--keyterm` — vocabulary hints, repeatable. Good for names.
- `--phonetic` — enables Double Metaphone matching. It's off by default because when I benchmarked it on my synthetic corpus it made things worse: short words like "and" and "end" share a phonetic key, and the aligner started gluing them together across long distances. On real transcripts with homophone mishearings it might pay off, but I can't promise that yet. Details in DESIGN.md.
- `--cache-dir` — where transcriptions are cached. Renaming a file doesn't bust the cache, it's keyed on content.

As a library:

```python
from anchor_align.pipeline import align_to_cues
from anchor_align.stt.cache import cached_transcribe
from anchor_align.stt.faster_whisper_adapter import FasterWhisperAdapter
from anchor_align.ingest.document import parse_transcript

adapter = FasterWhisperAdapter(model_size="base")
transcription = cached_transcribe(audio_path, "faster-whisper-base", adapter, STTOptions())
result = align_to_cues(transcription.words, parse_transcript(transcript_path))

result.cues          # the captions, ready to export
result.audio_order   # words in true audio order; the exporters want this list
result.issues        # every QC finding from all stages
```

There's a Streamlit demo for looking at the output visually:

```bash
streamlit run demo/app.py
```

And a Docker setup:

```bash
docker compose up demo
docker compose run --rm cli --batch /input --out /output
```

## Known gaps

These are tracked as open issues, so their status and any progress are visible:

- [Relocations that leave fewer than three anchors behind are not recovered](https://github.com/PatricR73/Anchor-Align/issues/1) — short or fragmented moves fall back to the older behavior for that span.
- [A run of orphan words at the start or end of a file collapses to a single timestamp and is dropped from the captions](https://github.com/PatricR73/Anchor-Align/issues/2) — flagged ZERO_DURATION_SPAN for human review.
- [No validation against real edited transcripts](https://github.com/PatricR73/Anchor-Align/issues/3) — every benchmark number comes from the synthetic corruption model.

## How it's organized

- `normalize/` — makes both streams comparable without losing the original text.
- `align/` — anchors, displaced-block chaining, the weighted Needleman-Wunsch, interpolation.
- `segment/` — the dynamic program that chops aligned words into cues.
- `ingest/`, `stt/`, `export/` — audio and transcript in, VTT/SRT/QC out.
- `benchmark/` — the corruption model and all the measurements.
- `pipeline.py`, `cli.py` — the one-call entry and the command line.

Why things are built the way they are: DESIGN.md. The methodology and full numbers: BENCHMARKS.md.

## Development

```bash
uv sync --frozen --all-extras --dev
pytest
ruff check .
mypy src/anchor_align
```

The full test run includes the benchmark comparisons and takes a few minutes. `pytest -k "not benchmark"` is the quick pass.

## License

MIT.
