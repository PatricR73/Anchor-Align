"""S7 — WhisperXAdapter/ElevenLabsAdapter: neither `whisperx` nor
`elevenlabs` is installed in this environment (both are optional extras),
so only the graceful-failure paths are actually verifiable here — the
happy-path wiring is unverified, see each adapter's own docstring."""

from __future__ import annotations

import importlib.util

import pytest

from anchor_align.exceptions import TranscriptionError
from anchor_align.models import STTOptions
from anchor_align.stt.elevenlabs_adapter import ElevenLabsAdapter
from anchor_align.stt.whisperx_adapter import WhisperXAdapter


@pytest.mark.skipif(
    importlib.util.find_spec("whisperx") is not None,
    reason="whisperx extra installed (uv sync --all-extras); the missing-package path is unverifiable",
)
def test_whisperx_adapter_raises_clear_import_error_when_package_missing(tmp_path):
    adapter = WhisperXAdapter()
    with pytest.raises(ImportError, match="whisperx"):
        adapter.transcribe(tmp_path / "audio.wav", STTOptions())


def test_elevenlabs_adapter_raises_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    adapter = ElevenLabsAdapter()
    with pytest.raises(TranscriptionError, match="API key"):
        adapter.transcribe(tmp_path / "audio.wav", STTOptions())


def test_elevenlabs_adapter_picks_up_env_var_api_key(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-123")
    adapter = ElevenLabsAdapter()
    assert adapter.api_key == "test-key-123"


def test_elevenlabs_adapter_explicit_key_overrides_env(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env-key")
    adapter = ElevenLabsAdapter(api_key="explicit-key")
    assert adapter.api_key == "explicit-key"


@pytest.mark.skipif(
    importlib.util.find_spec("elevenlabs") is not None,
    reason="elevenlabs extra installed (uv sync --all-extras); the missing-package path is unverifiable",
)
def test_elevenlabs_adapter_raises_clear_import_error_when_package_missing(tmp_path):
    adapter = ElevenLabsAdapter(api_key="fake-key")
    with pytest.raises(ImportError, match="elevenlabs"):
        adapter.transcribe(tmp_path / "audio.wav", STTOptions())
