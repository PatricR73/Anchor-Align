#!/usr/bin/env bash
# Regenerates the committed sample outputs in examples/ from the bundled
# sample pair (data/sample/).
#
# Requires: the anchor-align CLI on PATH (pip install -e ".[dev]"), and
# network access on the first run to download the faster-whisper model.
#
# Model size: base — the committed sample_output.* files were produced
# with this size, and the pipeline is deterministic for a given model
# (fresh-cache runs reproduce them byte for byte). Override with
# MODEL_SIZE=small bash scripts/regenerate_examples.sh if you want to
# compare sizes; the outputs will then differ from the committed ones.
# CACHE_DIR, if set, is passed through as the transcription cache
# location (useful where $HOME is read-only, e.g. CI).

set -euo pipefail
cd "$(dirname "$0")/.."

MODEL_SIZE="${MODEL_SIZE:-base}"
CACHE_ARGS=()
if [ -n "${CACHE_DIR:-}" ]; then
  CACHE_ARGS=(--cache-dir "$CACHE_DIR")
fi

anchor-align \
  data/sample/sample_audio.mp3 \
  data/sample/sample_transcript.txt \
  --model "$MODEL_SIZE" \
  "${CACHE_ARGS[@]}" \
  --out examples/

mv examples/captions.vtt examples/sample_output.vtt
mv examples/captions.srt examples/sample_output.srt
mv examples/captions.confidence.json examples/sample_output.confidence.json

echo "regenerated examples/ with faster-whisper model '$MODEL_SIZE'"
