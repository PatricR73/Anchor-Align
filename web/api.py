"""Web API for anchor-align.

Uploads audio + a human-edited transcript, runs the full pipeline
(transcribe -> align -> segment -> QC), and returns the complete result as
JSON: per-word alignment for the transcript heatmap, the produced cues, the
QC findings, and ready-to-download VTT/SRT/confidence artifacts. This is a
thin wiring layer exactly like demo/app.py — every call is into the
pipeline stages as their own tests exercise them.

Dev:  uvicorn web.api:app --port 8000   (Vite dev server proxies /api -> 8000)
Prod: serves web/ui/dist when it exists.
"""

from __future__ import annotations

import logging
import os
import shutil
import statistics
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from anchor_align.export.qc import write_confidence_json
from anchor_align.export.srt import write_srt
from anchor_align.export.vtt import write_vtt
from anchor_align.ingest.document import parse_transcript
from anchor_align.models import MatchType, STTOptions
from anchor_align.pipeline import align_to_cues
from anchor_align.stt.cache import cached_transcribe
from anchor_align.stt.faster_whisper_adapter import FasterWhisperAdapter
from anchor_align.normalize.normalizer import DoubleMetaphoneEncoder

logger = logging.getLogger("anchor_align.web")

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.environ.get("ANCHOR_ALIGN_CACHE_DIR", REPO_ROOT / ".cache" / "transcriptions"))
UPLOAD_DIR = REPO_ROOT / ".cache" / "uploads"
SAMPLE_AUDIO = REPO_ROOT / "data" / "sample" / "sample_audio.mp3"
SAMPLE_TRANSCRIPT = REPO_ROOT / "data" / "sample" / "sample_transcript.txt"
UI_DIST = Path(__file__).resolve().parent / "ui" / "dist"

MODELS = ("tiny", "base", "small", "medium")
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".mp4", ".flac", ".ogg"}
TRANSCRIPT_EXTS = {".txt", ".docx"}
_AUDIO_TTL_S = 60 * 60  # uploaded audio is kept for playback for one hour

app = FastAPI(title="anchor-align", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# id -> (path, expires_at) for audio served back to the browser for playback
_audio_registry: dict[str, tuple[Path, float]] = {}
_sample_payload: dict | None = None


def _register_audio(src: Path) -> str:
    now = time.time()
    for aid, (_, expires) in list(_audio_registry.items()):
        if expires < now:
            _audio_registry.pop(aid, None)
            try:
                (UPLOAD_DIR / aid).unlink(missing_ok=True)
            except OSError:
                pass
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    aid = uuid.uuid4().hex[:16]
    dest = UPLOAD_DIR / f"{aid}{src.suffix.lower()}"
    shutil.copy2(src, dest)
    _audio_registry[aid] = (dest, now + _AUDIO_TTL_S)
    return aid


def _build_payload(
    *,
    audio_name: str,
    transcript_name: str,
    model: str,
    phonetic: bool,
    audio_id: str,
    audio_duration_s: float,
    elapsed_s: float,
    result,
) -> dict:
    edited_order = sorted(result.aligned, key=lambda w: w.token.index)
    aligned = [
        {
            "text": w.token.text,
            "index": w.token.index,
            "char_offset": w.token.char_offset,
            "sentence_id": w.token.sentence_id,
            "is_sentence_end": w.token.is_sentence_end,
            "match_type": w.match_type.value,
            "confidence": round(w.confidence, 4),
            "start": round(w.start, 3),
            "end": round(w.end, 3),
        }
        for w in edited_order
    ]
    cues = [
        {
            "index": c.index,
            "start": round(c.start, 3),
            "end": round(c.end, 3),
            "lines": list(c.lines),
        }
        for c in result.cues
    ]
    issues = [
        {"severity": i.severity, "code": i.code.value, "message": i.message, "cue_index": i.cue_index}
        for i in result.issues
    ]
    confidences = [w.confidence for w in result.audio_order]
    stats = {
        "cues": len(result.cues),
        "qc_errors": result.error_count,
        "qc_warnings": result.warning_count,
        "interpolated_words": sum(1 for w in result.aligned if w.match_type == MatchType.INTERPOLATED),
        "mean_confidence": round(statistics.mean(confidences), 4) if confidences else None,
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        write_vtt(result.cues, tmp_dir / "captions.vtt")
        write_srt(result.cues, tmp_dir / "captions.srt")
        write_confidence_json(result.cues, result.audio_order, tmp_dir / "confidence.json")
        downloads = {
            "vtt": (tmp_dir / "captions.vtt").read_text(encoding="utf-8"),
            "srt": (tmp_dir / "captions.srt").read_text(encoding="utf-8"),
            "confidence": (tmp_dir / "confidence.json").read_text(encoding="utf-8"),
        }

    return {
        "audio_id": audio_id,
        "audio_name": audio_name,
        "transcript_name": transcript_name,
        "model": model,
        "phonetic": phonetic,
        "elapsed_s": round(elapsed_s, 2),
        "audio_duration_s": round(audio_duration_s, 3),
        "stats": stats,
        "aligned": aligned,
        "cues": cues,
        "issues": issues,
        "downloads": downloads,
    }


def _run_pipeline(audio_path: Path, transcript_path: Path, model: str, phonetic: bool, keyterms: list[str]):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    adapter = FasterWhisperAdapter(model_size=model)
    transcription = cached_transcribe(
        audio_path,
        f"faster-whisper-{model}",
        adapter,
        STTOptions(keyterms=keyterms),
        cache_dir=CACHE_DIR,
    )
    edited_tokens = parse_transcript(transcript_path)
    result = align_to_cues(
        transcription.words,
        edited_tokens,
        phonetic_encoder=DoubleMetaphoneEncoder() if phonetic else None,
    )
    return transcription, result


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/align")
def align(
    audio: UploadFile = File(...),
    transcript: UploadFile = File(...),
    model: str = Form("base"),
    phonetic: bool = Form(False),
    keyterms: str = Form(""),
) -> dict:
    audio_ext = Path(audio.filename or "").suffix.lower()
    transcript_ext = Path(transcript.filename or "").suffix.lower()
    if audio_ext not in AUDIO_EXTS:
        raise HTTPException(400, f"audio must be one of {sorted(AUDIO_EXTS)} (got '{audio.filename}')")
    if transcript_ext not in TRANSCRIPT_EXTS:
        raise HTTPException(400, f"transcript must be one of {sorted(TRANSCRIPT_EXTS)} (got '{transcript.filename}')")
    if model not in MODELS:
        raise HTTPException(400, f"model must be one of {list(MODELS)} (got '{model}')")

    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        audio_path = tmp_dir / f"audio{audio_ext}"
        audio_path.write_bytes(audio.file.read())
        transcript_path = tmp_dir / f"transcript{transcript_ext}"
        transcript_path.write_bytes(transcript.file.read())
        try:
            transcription, result = _run_pipeline(
                audio_path, transcript_path, model, phonetic,
                [k.strip() for k in keyterms.split(",") if k.strip()],
            )
        except Exception as exc:  # noqa: BLE001 — surfaced to the user, not swallowed
            logger.exception("pipeline failed for %s", audio.filename)
            raise HTTPException(500, f"Pipeline failed: {exc}") from exc
        audio_id = _register_audio(audio_path)
        return _build_payload(
            audio_name=audio.filename or "audio",
            transcript_name=transcript.filename or "transcript",
            model=model,
            phonetic=phonetic,
            audio_id=audio_id,
            audio_duration_s=transcription.audio_duration,
            elapsed_s=time.time() - started,
            result=result,
        )


@app.get("/api/sample")
def sample() -> dict:
    """Run the bundled sample pair (data/sample) through the full pipeline
    and return the same payload shape as /api/align. Computed once, cached
    in memory afterwards."""
    global _sample_payload
    if _sample_payload is None:
        started = time.time()
        try:
            transcription, result = _run_pipeline(SAMPLE_AUDIO, SAMPLE_TRANSCRIPT, "base", False, [])
        except Exception as exc:  # noqa: BLE001
            logger.exception("sample pipeline failed")
            raise HTTPException(500, f"Sample failed: {exc}") from exc
        audio_id = _register_audio(SAMPLE_AUDIO)
        _sample_payload = _build_payload(
            audio_name=SAMPLE_AUDIO.name,
            transcript_name=SAMPLE_TRANSCRIPT.name,
            model="base",
            phonetic=False,
            audio_id=audio_id,
            audio_duration_s=transcription.audio_duration,
            elapsed_s=time.time() - started,
            result=result,
        )
    return _sample_payload


@app.get("/api/audio/{audio_id}")
def audio(audio_id: str) -> FileResponse:
    entry = _audio_registry.get(audio_id)
    if entry is None:
        raise HTTPException(404, "audio not found or expired")
    path, _ = entry
    return FileResponse(path)


if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
