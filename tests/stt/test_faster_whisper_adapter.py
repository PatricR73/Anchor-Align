"""S7 — FasterWhisperAdapter, tested against a mocked WhisperModel (no
network/model download in tests — that's an integration concern, not a
unit-test one)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar
from unittest.mock import patch

from anchor_align.models import STTOptions
from anchor_align.stt.faster_whisper_adapter import FasterWhisperAdapter


@dataclass
class _FakeWord:
    start: float
    end: float
    word: str
    probability: float


@dataclass
class _FakeSegment:
    words: list[_FakeWord] = field(default_factory=list)


@dataclass
class _FakeInfo:
    language: str = "en"
    duration: float = 3.0


class _FakeWhisperModel:
    # deliberately class-level, not per-instance: tests read these off the
    # class after `transcribe()` runs, with no instance reference in hand
    last_init_args: ClassVar[tuple] = ()
    last_transcribe_kwargs: ClassVar[dict] = {}

    def __init__(self, model_size, device, compute_type):
        _FakeWhisperModel.last_init_args = (model_size, device, compute_type)

    def transcribe(self, audio_str, **kwargs):
        _FakeWhisperModel.last_transcribe_kwargs = kwargs
        segments = [
            _FakeSegment(words=[_FakeWord(0.0, 0.5, " Hello", 0.95), _FakeWord(0.5, 1.0, " world", 0.88)]),
        ]
        return segments, _FakeInfo()


def test_transcribe_returns_words_with_stripped_text_and_timing(tmp_path):
    with patch("faster_whisper.WhisperModel", _FakeWhisperModel):
        adapter = FasterWhisperAdapter()
        result = adapter.transcribe(tmp_path / "audio.wav", STTOptions())

    assert [w.text for w in result.words] == ["Hello", "world"]
    assert result.words[0].start == 0.0
    assert result.words[0].end == 0.5
    assert result.words[0].confidence == 0.95


def test_transcribe_sets_model_id_and_metadata(tmp_path):
    with patch("faster_whisper.WhisperModel", _FakeWhisperModel):
        adapter = FasterWhisperAdapter(model_size="small")
        result = adapter.transcribe(tmp_path / "audio.wav", STTOptions())

    assert result.model_id == "faster-whisper-small"
    assert result.language == "en"
    assert result.audio_duration == 3.0


def test_keyterms_passed_as_initial_prompt(tmp_path):
    with patch("faster_whisper.WhisperModel", _FakeWhisperModel):
        adapter = FasterWhisperAdapter()
        adapter.transcribe(tmp_path / "audio.wav", STTOptions(keyterms=["Siobhan", "Yosemite"]))

    assert _FakeWhisperModel.last_transcribe_kwargs["initial_prompt"] == "Siobhan, Yosemite"


def test_no_keyterms_means_no_initial_prompt(tmp_path):
    with patch("faster_whisper.WhisperModel", _FakeWhisperModel):
        adapter = FasterWhisperAdapter()
        adapter.transcribe(tmp_path / "audio.wav", STTOptions())

    assert _FakeWhisperModel.last_transcribe_kwargs["initial_prompt"] is None


def test_model_size_device_compute_type_passed_to_whisper_model(tmp_path):
    with patch("faster_whisper.WhisperModel", _FakeWhisperModel):
        adapter = FasterWhisperAdapter(model_size="large-v3", device="cuda", compute_type="float16")
        adapter.transcribe(tmp_path / "audio.wav", STTOptions())

    assert _FakeWhisperModel.last_init_args == ("large-v3", "cuda", "float16")
