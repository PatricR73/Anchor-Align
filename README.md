# anchor-align

Takes a transcript that an editor cleaned up and the word timings from speech-to-text, and figures out where each edited word actually falls in the audio. Then it turns that into VTT cues.

## The problem this solves

Speech-to-text gives you timestamps for every word that was said. Then a human editor fixes the transcript: drops the "um"s, corrects the names, moves a sentence to a better place. The edited text reads properly now, but it no longer matches the STT output word for word, and the STT output is the only thing carrying timing. So you have a good transcript with no timing, and a timed transcript nobody wants to caption.

This project bridges that. It recovers, for every word in the edited transcript, the timestamp it should have, and it's designed to survive both small text changes and whole sentences being moved around. The cues it produces obey the usual caption constraints (two lines max, 42 characters per line, one to seven seconds, 21 characters per second) and never overlap.

## Does it actually work?

Short version:

- On a long recording (40+ minutes), the naive approach's timing error at the end of the file is about three times what it is near the start. Error accumulates. anchor-align's stays flat, because it periodically re-anchors against words it's confident about.
- When the editor moved a paragraph around, worst-case timing error went from about 20 seconds down to about 7 seconds, compared to the naive baseline. And when a moved block is recovered properly, the timing inside it is exact.

![Drift: body vs tail error, untouched tokens only](benchmarks/results/drift_not_touched.png)

![Mean boundary error vs corruption level](benchmarks/results/mean_error_vs_level.png)

Both claims come with caveats, and they're spelled out in BENCHMARKS.md. The headline caveat: the benchmark corpus is synthetic. I corrupt clean transcripts with edits I chose, then measure against that. There's no validation against real edited transcripts yet, and that's the biggest open item. Read the caveats before quoting numbers.

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

- Relocations that leave fewer than three anchors behind are not recovered. A short or heavily fragmented move falls back to the older behavior for that span. This is the one structural gap I know about and haven't closed.
- A run of orphan words at the very beginning or end, with no anchor on either side, collapses to a single timestamp. Those words are dropped from the captions and flagged ZERO_DURATION_SPAN. They don't get fake timing, which is the right call, but it means a human has to review that spot.
- No validation on real transcripts. I keep saying this because it's the most important one.

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
