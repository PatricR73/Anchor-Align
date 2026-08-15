"""S7 — optional STT adapter: ElevenLabs. Demonstrates the abstraction is
swappable, not a hard requirement of the pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from anchor_align.exceptions import TranscriptionError
from anchor_align.models import STTOptions, STTWord, Transcription


class ElevenLabsAdapter:
    """Implements the STTProvider protocol.

    Requires the `elevenlabs` extra (`pip install anchor-align[elevenlabs]`)
    and an `ELEVENLABS_API_KEY` environment variable — deferred to call
    time for the same reason as WhisperXAdapter's import.

    The wiring below follows the ElevenLabs SDK's documented speech-to-text
    API but is unverified in this environment — `elevenlabs` isn't
    installed here and this adapter also needs a real API key and network
    access to exercise end to end. Only the missing-dependency and
    missing-API-key failure paths have actual tests.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")

    def transcribe(self, audio: Path, opts: STTOptions) -> Transcription:
        if not self.api_key:
            raise TranscriptionError(
                "ElevenLabsAdapter requires an API key: pass api_key= or set ELEVENLABS_API_KEY"
            )
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as e:
            raise ImportError(
                "ElevenLabsAdapter requires the 'elevenlabs' extra: pip install anchor-align[elevenlabs]"
            ) from e

        client = ElevenLabs(api_key=self.api_key)
        with audio.open("rb") as f:
            response = client.speech_to_text.convert(
                file=f,
                model_id="scribe_v1",
                language_code=opts.language,
            )

        words: list[STTWord] = []
        for w in getattr(response, "words", []) or []:
            if w.type != "word":
                continue  # ElevenLabs also emits "spacing" entries between words
            words.append(STTWord(text=w.text.strip(), start=w.start, end=w.end, confidence=1.0))

        return Transcription(
            words=words,
            model_id="elevenlabs-scribe_v1",
            audio_duration=words[-1].end if words else 0.0,
            language=opts.language,
        )
