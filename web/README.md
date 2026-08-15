# anchor-align web app

A browser front end for the anchor-align pipeline, replacing the Streamlit
demo: upload audio + a human-edited transcript, run the full pipeline, and
inspect the result — a confidence heatmap over the transcript (click a word
to seek), a word-timeline scrubber with a live playhead, the produced cue
list, the QC findings, and VTT/SRT/confidence-JSON downloads.

Two parts, both in this directory:

- api.py — FastAPI app. A thin wiring layer over the pipeline stages,
  exactly like demo/app.py; no alignment logic lives here.
- ui/ — Vite + React + TypeScript + Tailwind v4 front end.

## Run (development)

```bash
# 1. API on :8000 (transcription cache lives in .cache/transcriptions)
HF_HUB_OFFLINE=1 .venv/bin/uvicorn web.api:app --port 8000

# 2. Front end on :5173 (proxies /api -> :8000)
cd web/ui && npm install && npm run dev
```

Open http://127.0.0.1:5173. The bundled sample (data/sample/) can be
run with one click from the home screen.

## Run (production)

```bash
cd web/ui && npm run build     # emits ui/dist
HF_HUB_OFFLINE=1 .venv/bin/uvicorn web.api:app --port 8000
```

FastAPI serves ui/dist at / when it exists, plus the API under /api.
HF_HUB_OFFLINE=1 makes faster-whisper use the locally cached model instead
of hitting Hugging Face.

## API

| Endpoint | Description |
|---|---|
| POST /api/align | multipart audio, transcript, model, phonetic -> full result JSON |
| GET /api/sample | runs the bundled sample pair, same payload shape |
| GET /api/audio/{id} | streams the uploaded audio back for playback |
| GET /api/health | liveness |

The result payload carries per-word alignment (edited order), the cues,
QC issues, stats, and ready-made VTT/SRT/confidence-JSON download strings.

## Tooling

- tools/shot.mjs — screenshot: node tools/shot.mjs <url> <out> [w] [h]
- tools/audit.mjs — a11y/contrast/overflow checks:
  node tools/audit.mjs <url> [width] [sample]
- tools/demo-shoot.mjs — drives idle -> sample -> every tab at desktop and
  mobile, verifies seek/play/download, and captures .shots/*.png.
- tools/test-missing-token.mjs — regression for the active-word highlight
  being position-based: serves a payload with token index 5 missing and
  asserts the correct word highlights (plus the dev-mode invariant tripwire
  fires).

Screenshots go to .shots/ at the repo root (gitignored).
