"""S7 — disk cache for transcriptions (diskcache), so the same audio is
never re-transcribed while alignment is iterated on."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import diskcache

from anchor_align.interfaces import STTProvider
from anchor_align.models import STTOptions, Transcription

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "anchor_align" / "transcriptions"


def _cache_key(audio_path: Path, adapter_name: str, opts: STTOptions) -> str:
    """Content hash of the audio file, not its path — a renamed or moved
    file with identical bytes must still hit the cache. `adapter_name` and
    `opts` are folded in too: different models/options on the same audio
    produce different transcriptions, not a cache collision."""
    h = hashlib.sha256()
    with audio_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    h.update(adapter_name.encode())
    h.update(opts.model_dump_json().encode())
    return h.hexdigest()


def cached_transcribe(
    audio_path: Path,
    adapter_name: str,
    provider: STTProvider,
    opts: STTOptions,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Transcription:
    """Return the cached `Transcription` for (audio content, adapter_name,
    opts) if present, else run `provider.transcribe` and cache the result.

    `provider` must be the `STTProvider` implementation `adapter_name`
    names — this function doesn't dispatch on the name itself; `adapter_name`
    exists purely as a stable cache-key discriminator between providers.
    """
    key = _cache_key(audio_path, adapter_name, opts)
    with diskcache.Cache(str(cache_dir)) as cache:
        cached = cache.get(key)
        if cached is not None:
            logger.info("transcription cache hit for %s", audio_path)
            return Transcription.model_validate_json(cached)
        logger.info("transcription cache miss for %s; calling %s", audio_path, adapter_name)
        result = provider.transcribe(audio_path, opts)
        cache.set(key, result.model_dump_json())
        return result
