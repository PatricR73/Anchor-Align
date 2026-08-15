# Sample output

These three files are the genuine output of the pipeline run on the
bundled sample pair:

- `data/sample/sample_audio.mp3` — 33.864 s of speech
- `data/sample/sample_transcript.txt` — an edited transcript, 77 words

Command that produced them:

    anchor-align data/sample/sample_audio.mp3 data/sample/sample_transcript.txt --out examples/

- Model: faster-whisper `base` (the CLI default)
- Package version: 0.1.0
- Result: 77 edited words segmented into 6 cues; the QC pass found 0
  errors and 0 warnings

Re-running the command reproduces these files byte for byte, verified
against a fresh transcription cache. `scripts/regenerate_examples.sh`
wraps the command.

The three files are the same content in three formats. `sample_output.vtt`
and `sample_output.srt` are the captions in the two file formats.
`sample_output.confidence.json` is the per-cue QC signal: mean and minimum
word confidence for each cue, and how many words it covers.

## Reading the confidence JSON

Take cue 1. The edited transcript opens with:

    Hi, my name is Joanna and I work on a transcript alignment project.

`sample_output.vtt` recovers that sentence in the audio and wraps it
within the two-line, 42-character limit:

    1
    00:00:00.000 --> 00:00:06.240
    Hi, my name is Joanna and I work on
    a transcript alignment project. Last

The cue also pulls "Last", the first word of the next sentence, because
the segmenter fits lines, not sentences.

The matching entry in `sample_output.confidence.json`:

```json
{
  "cue_index": 1,
  "start": 0.0,
  "end": 6.24,
  "mean_confidence": 0.9642857142857143,
  "min_confidence": 0.95,
  "word_count": 14
}
```

All 14 words in this cue were matched to real STT words, so the recovered
timing 0.000-6.240 is backed by direct speech-to-text evidence: the
least-confident word still scored 0.95, and none fell back to
interpolation. That is what `min_confidence` is for.

Contrast cue 2, whose `min_confidence` is 0.0: one word in it, `"I`, had
no usable STT match and was timed by interpolation, which assigns
confidence 0.0 by design. A cue with `min_confidence: 0.0` is the place
to look first when reviewing output.
