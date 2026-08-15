"""S7 — optional STT adapter: WhisperX forced alignment (wav2vec2) for more
precise word-level timestamps than raw Whisper decoding."""

from __future__ import annotations

from pathlib import Path

from anchor_align.models import STTOptions, STTWord, Transcription


class WhisperXAdapter:
    """Implements the STTProvider protocol.

    Requires the `whisperx` extra (`pip install anchor-align[whisperx]`) —
    not a core dependency, so importing it is deferred to call time rather
    than module load time.

    The wiring below follows whisperx's documented two-stage API
    (transcribe with a Whisper model, then align word-level timestamps
    with a wav2vec2 model) but is unverified in this environment —
    `whisperx` isn't installed here, so only the missing-dependency
    failure path has an actual test. Verify against a real whisperx
    install before relying on this in production.
    """

    def __init__(self, model_size: str = "base", device: str = "cpu"):
        self.model_size = model_size
        self.device = device

    def transcribe(self, audio: Path, opts: STTOptions) -> Transcription:
        try:
            import whisperx
        except ImportError as e:
            raise ImportError(
                "WhisperXAdapter requires the 'whisperx' extra: pip install anchor-align[whisperx]"
            ) from e

        model = whisperx.load_model(self.model_size, self.device, language=opts.language)
        audio_array = whisperx.load_audio(str(audio))
        result = model.transcribe(audio_array)

        align_model, metadata = whisperx.load_align_model(
            language_code=result["language"], device=self.device
        )
        aligned = whisperx.align(result["segments"], align_model, metadata, audio_array, self.device)

        words: list[STTWord] = []
        for segment in aligned["segments"]:
            for w in segment.get("words", []):
                if "start" not in w or "end" not in w:
                    continue  # whisperx drops timing for a word it couldn't align
                words.append(
                    STTWord(text=w["word"].strip(), start=w["start"], end=w["end"], confidence=w.get("score", 1.0))
                )

        return Transcription(
            words=words,
            model_id=f"whisperx-{self.model_size}",
            audio_duration=words[-1].end if words else 0.0,
            language=result.get("language"),
        )
