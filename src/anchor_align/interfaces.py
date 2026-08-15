"""Abstract interfaces implemented by later segments.

Defining these up front is what lets the pipeline stages be built and
tested in isolation against a fixed contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from anchor_align.models import (
    AlignedWord,
    Cue,
    EditedToken,
    QCIssue,
    STTOptions,
    STTWord,
    Transcription,
)


class STTProvider(Protocol):
    """Implemented by the STT adapters (faster-whisper / WhisperX /
    ElevenLabs). Synchronous by design: transcription here is a one-shot
    batch job run from a CLI, not a live service."""

    def transcribe(self, audio: Path, opts: STTOptions) -> Transcription: ...


class TranscriptExtractor(Protocol):
    """Implemented by transcript ingest (DOCX/TXT parsing)."""

    def extract(self, path: Path) -> list[EditedToken]: ...


class PhoneticEncoder(Protocol):
    """Implemented by phonetic-key strategies plugged into normalization
    rather than hardcoded, so they can be benchmarked against each other.
    Returns a variadic tuple: zero keys for a null encoder, two for Double
    Metaphone, one for a phonemic encoder."""

    def encode(self, token: str) -> tuple[str, ...]: ...


class Aligner(Protocol):
    """Implemented by S3: the alignment engine's public entry point.

    `phonetic_encoder` defaults to `NullEncoder`; pass
    `DoubleMetaphoneEncoder()` to enable phonetic matching (opt-in by
    measurement — see the implementation's docstring).
    """

    def align(
        self,
        stt_words: list[STTWord],
        edited_tokens: list[EditedToken],
        *,
        phonetic_encoder: PhoneticEncoder,
    ) -> list[AlignedWord]: ...


class CueBuilder(Protocol):
    """Implemented by S5: segments aligned words into cues."""

    def build_cues(self, words: list[AlignedWord]) -> list[Cue]: ...


class QCRule(Protocol):
    """Implemented by S8: one QC check over the produced cues."""

    def check(self, cues: list[Cue]) -> list[QCIssue]: ...


class Writer(Protocol):
    """Implemented by S8: renders cues to a caption file format."""

    def write(self, cues: list[Cue], output_path: Path) -> Path: ...
