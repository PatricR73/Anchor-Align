"""S7 — default STT adapter: faster-whisper. Runs with no API key."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from anchor_align.models import STTOptions, STTWord, Transcription

logger = logging.getLogger(__name__)

DEFAULT_MODEL_SIZE = "base"


class FasterWhisperAdapter:
    """Implements the STTProvider protocol.

    `model_size`/`device`/`compute_type` are constructor args, not part of
    `STTOptions` (that's per-call vocabulary/language/diarization hints,
    not model selection). The underlying WhisperModel is loaded lazily on
    first use and reused across calls — reloading per transcription would
    pay the download/load cost every time.
    """

    def __init__(self, model_size: str = DEFAULT_MODEL_SIZE, device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
            logger.info("loaded faster-whisper model %s (device=%s, compute=%s)", self.model_size, self.device, self.compute_type)
        return self._model

    def transcribe(self, audio: Path, opts: STTOptions) -> Transcription:
        model = self._load_model()
        segments, info = model.transcribe(
            str(audio),
            language=opts.language,
            word_timestamps=True,
            # keyterms as an initial prompt is the only hook faster-whisper
            # (a Whisper wrapper, not a keyterm-boosting API like Deepgram's)
            # exposes for biasing recognition toward specific vocabulary.
            initial_prompt=", ".join(opts.keyterms) if opts.keyterms else None,
        )

        words: list[STTWord] = []
        for segment in segments:
            if not segment.words:
                continue
            for w in segment.words:
                words.append(
                    STTWord(text=w.word.strip(), start=w.start, end=w.end, confidence=_prob_to_confidence(w.probability))
                )

        return Transcription(
            words=words,
            model_id=f"faster-whisper-{self.model_size}",
            audio_duration=info.duration,
            language=info.language,
        )


def _prob_to_confidence(probability: float) -> float:
    """faster-whisper's word probability is already a [0, 1] confidence,
    not a log-probability — clamped defensively since floating-point noise
    can push it a hair outside [0, 1] and STTWord.confidence rejects that."""
    return max(0.0, min(1.0, probability))
