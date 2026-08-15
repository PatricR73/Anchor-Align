"""S7 — cached_transcribe: cache hit/miss behavior against a fake
STTProvider that counts its own calls, since the point being tested is
"does the cache actually avoid re-transcribing", not any real STT engine.
"""

from __future__ import annotations

from anchor_align.models import STTOptions, STTWord, Transcription
from anchor_align.stt.cache import cached_transcribe


class _CountingProvider:
    def __init__(self):
        self.call_count = 0

    def transcribe(self, audio, opts):
        self.call_count += 1
        return Transcription(
            words=[STTWord(text="hello", start=0.0, end=1.0)],
            model_id="fake-model",
            audio_duration=1.0,
            language=opts.language,
        )


def _make_audio(path, content=b"fake audio bytes"):
    path.write_bytes(content)
    return path


def test_second_call_is_a_cache_hit_and_does_not_call_provider(tmp_path):
    audio = _make_audio(tmp_path / "a.wav")
    cache_dir = tmp_path / "cache"
    provider = _CountingProvider()
    opts = STTOptions()

    first = cached_transcribe(audio, "fake-adapter", provider, opts, cache_dir=cache_dir)
    second = cached_transcribe(audio, "fake-adapter", provider, opts, cache_dir=cache_dir)

    assert provider.call_count == 1
    assert first == second


def test_different_audio_content_is_a_cache_miss(tmp_path):
    cache_dir = tmp_path / "cache"
    provider = _CountingProvider()
    opts = STTOptions()

    audio_a = _make_audio(tmp_path / "a.wav", b"content A")
    audio_b = _make_audio(tmp_path / "b.wav", b"content B")

    cached_transcribe(audio_a, "fake-adapter", provider, opts, cache_dir=cache_dir)
    cached_transcribe(audio_b, "fake-adapter", provider, opts, cache_dir=cache_dir)

    assert provider.call_count == 2


def test_same_content_different_path_is_a_cache_hit(tmp_path):
    """Content hash, not path — a renamed/moved file with identical bytes
    must still hit the cache."""
    cache_dir = tmp_path / "cache"
    provider = _CountingProvider()
    opts = STTOptions()

    audio_a = _make_audio(tmp_path / "original_name.wav", b"same bytes")
    audio_b = _make_audio(tmp_path / "renamed.wav", b"same bytes")

    cached_transcribe(audio_a, "fake-adapter", provider, opts, cache_dir=cache_dir)
    cached_transcribe(audio_b, "fake-adapter", provider, opts, cache_dir=cache_dir)

    assert provider.call_count == 1


def test_different_adapter_name_is_a_cache_miss(tmp_path):
    audio = _make_audio(tmp_path / "a.wav")
    cache_dir = tmp_path / "cache"
    provider = _CountingProvider()
    opts = STTOptions()

    cached_transcribe(audio, "adapter-a", provider, opts, cache_dir=cache_dir)
    cached_transcribe(audio, "adapter-b", provider, opts, cache_dir=cache_dir)

    assert provider.call_count == 2


def test_different_opts_is_a_cache_miss(tmp_path):
    audio = _make_audio(tmp_path / "a.wav")
    cache_dir = tmp_path / "cache"
    provider = _CountingProvider()

    cached_transcribe(audio, "fake-adapter", provider, STTOptions(language="en"), cache_dir=cache_dir)
    cached_transcribe(audio, "fake-adapter", provider, STTOptions(language="ro"), cache_dir=cache_dir)

    assert provider.call_count == 2


def test_cached_result_round_trips_exactly(tmp_path):
    audio = _make_audio(tmp_path / "a.wav")
    cache_dir = tmp_path / "cache"
    provider = _CountingProvider()
    opts = STTOptions(language="en")

    first = cached_transcribe(audio, "fake-adapter", provider, opts, cache_dir=cache_dir)
    second = cached_transcribe(audio, "fake-adapter", provider, opts, cache_dir=cache_dir)

    assert second.words == first.words
    assert second.model_id == first.model_id
    assert second.language == first.language
