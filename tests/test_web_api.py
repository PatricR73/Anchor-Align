"""Regression tests for the web API audio registry (web/api.py).

Two TTL bugs fixed together:

* Bug A — the reaper unlinked the bare id while files are written as
  id + suffix, so the unlink never matched, missing_ok=True swallowed the
  miss, and every upload leaked to disk permanently. The registry tuple
  already holds the real path; the reaper now unlinks that.

* Bug B — the permanently-cached /api/sample payload baked in a TTL-bound
  audio_id. After an hour of uptime, any registration reaped the sample's
  audio entry and the cached payload served a dead id (404, no error state)
  until restart. The sample routes now re-register on a cache hit when the
  cached id is no longer live, and rewrite the id.

Both tests use the injected _now clock (web.api._now) so the TTL can be
advanced deterministically without sleeping.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web.api as api
from anchor_align.export.srt import format_srt, write_srt
from anchor_align.export.vtt import format_vtt, write_vtt


def _fake_pipeline_result() -> tuple[SimpleNamespace, SimpleNamespace]:
    """One word, one cue — enough for _build_payload and the exporters."""
    word = SimpleNamespace(
        token=SimpleNamespace(
            text="hi",
            index=0,
            char_offset=0,
            sentence_id=0,
            is_sentence_end=True,
        ),
        match_type=SimpleNamespace(value="exact"),
        confidence=0.99,
        start=0.0,
        end=0.3,
    )
    cue = SimpleNamespace(index=1, start=0.0, end=0.3, lines=["hi"], word_span=(0, 1))
    transcription = SimpleNamespace(audio_duration=0.3)
    result = SimpleNamespace(
        aligned=[word],
        audio_order=[word],
        cues=[cue],
        issues=[],
        error_count=0,
        warning_count=0,
    )
    return transcription, result


def _advance_clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(api, "_now", lambda: clock["t"])
    return clock


def test_reaper_deletes_expired_upload(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """An expired registration is removed from the registry AND from disk.

    Regression for Bug A: the reaper unlinked UPLOAD_DIR / aid while files
    are written as UPLOAD_DIR / f"{aid}{suffix}", so the miss was swallowed
    by missing_ok=True and the file leaked to disk permanently.
    """
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(api, "_audio_registry", {})
    clock = _advance_clock(monkeypatch)

    src = tmp_path / "one.wav"
    src.write_bytes(b"audio-one")
    aid = api._register_audio(src)
    assert (api.UPLOAD_DIR / f"{aid}.wav").exists()

    clock["t"] += api._AUDIO_TTL_S + 1  # advance past the TTL

    second = tmp_path / "two.mp3"
    second.write_bytes(b"audio-two")
    api._register_audio(second)  # registration runs the reaper

    assert aid not in api._audio_registry
    assert not (api.UPLOAD_DIR / f"{aid}.wav").exists()  # expired file gone from disk


def test_adapter_cache_is_process_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """One FasterWhisperAdapter per model size, shared across requests.

    Regression for constructing an adapter per request: a new adapter means
    the lazy WhisperModel load is paid on every transcription-cache miss.
    """
    constructed: list[str] = []

    class _FakeAdapter:
        def __init__(self, model_size: str) -> None:
            self.model_size = model_size
            constructed.append(model_size)

    monkeypatch.setattr(api, "FasterWhisperAdapter", _FakeAdapter)
    monkeypatch.setattr(api, "_adapters", {})
    monkeypatch.setattr(api, "_adapter_locks", {})

    first = api._get_adapter("base")
    second = api._get_adapter("base")
    other = api._get_adapter("medium")

    assert first is second
    assert first is not other
    assert constructed == ["base", "medium"]  # each size constructed exactly once


def test_sample_audio_id_survives_ttl(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cached /api/sample payload never serves a dead audio_id.

    Regression for Bug B: after _AUDIO_TTL_S of uptime, a registration
    reaped the sample's audio entry; the permanently-cached payload then
    pointed at an id that 404'd until restart. The sample route now
    re-registers on a cache hit when the cached id is no longer live.

    Sequence: serve /api/sample -> advance the clock past the TTL -> register
    an upload (reaper purges the sample's audio) -> serve /api/sample again.
    Asserts (a) the expired file is gone from disk and (b) the second
    payload's audio_id answers GET /api/audio/{id} with 200.
    """
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(api, "_audio_registry", {})
    monkeypatch.setattr(api, "_sample_payload", None)
    monkeypatch.setattr(api, "_run_pipeline", lambda *a, **k: _fake_pipeline_result())
    # the lifespan handler warms the default model; stub it so the test
    # does not load faster-whisper (~3 s, ~500 MB)
    monkeypatch.setattr(api, "_get_adapter", lambda model: None)
    clock = _advance_clock(monkeypatch)

    with TestClient(api.app) as client:
        first = client.get("/api/sample")
        assert first.status_code == 200
        first_id = first.json()["audio_id"]
        first_path = api._audio_registry[first_id][0]
        assert client.get(f"/api/audio/{first_id}").status_code == 200

        clock["t"] += api._AUDIO_TTL_S + 1  # an hour of uptime passes

        upload = tmp_path / "up.wav"
        upload.write_bytes(b"upload")
        api._register_audio(upload)  # reaper purges the sample's entry
        assert first_id not in api._audio_registry
        assert not first_path.exists()  # (a) expired file gone from disk

        second = client.get("/api/sample")
        assert second.status_code == 200
        second_id = second.json()["audio_id"]
        assert second_id != first_id  # the cached id was rewritten
        assert client.get(f"/api/audio/{second_id}").status_code == 200  # (b)
def test_error_bodies_never_leak_filesystem_paths(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """No 4xx/5xx response body may contain a filesystem path.

    Regression for HTTPException(500, f"Pipeline failed: {exc}"), which put
    internal exception text (potentially filesystem paths) on the wire. All
    error responses now carry a stable machine-readable code plus a safe
    message; the detail is logged server-side only.
    """
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(api, "_audio_registry", {})
    monkeypatch.setattr(api, "_get_adapter", lambda model: None)
    secret_path = "/home/retrix/.venv/lib/python3.11/site-packages/faster_whisper/model.py:64"

    def boom(*a: object, **k: object) -> None:
        raise RuntimeError(secret_path + " exploded in the pipeline")

    monkeypatch.setattr(api, "_run_pipeline", boom)

    with TestClient(api.app) as client:
        bodies: list[str] = []

        # 400: unsupported extension -> INVALID_UPLOAD
        resp = client.post(
            "/api/align",
            files={"audio": ("x.exe", b"x", "application/octet-stream"), "transcript": ("t.txt", b"hello")},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_UPLOAD"
        bodies.append(resp.text)

        # 413: per-part limit exceeded while streaming -> UPLOAD_TOO_LARGE
        monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 10)
        resp = client.post(
            "/api/align",
            files={"audio": ("a.wav", b"0" * 100, "audio/wav"), "transcript": ("t.txt", b"hello")},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"
        bodies.append(resp.text)
        monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 1 << 30)

        # 500: pipeline failure whose message contains a filesystem path
        resp = client.post(
            "/api/align",
            files={"audio": ("a.wav", b"aaa", "audio/wav"), "transcript": ("t.txt", b"hello")},
        )
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "PIPELINE_FAILED"
        assert secret_path not in resp.text
        bodies.append(resp.text)

    for body in bodies:
        assert secret_path not in body
        assert "/home/" not in body
        assert ".venv" not in body
        assert "src/anchor_align" not in body
        assert str(api.REPO_ROOT) not in body
def test_middleware_rejects_oversized_body_before_parse(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """The middleware 413s on a declared-oversized Content-Length without
    consuming the body, so nothing is buffered. (The per-chunk check covers
    requests without a Content-Length; this covers the declared case.)"""
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(api, "_audio_registry", {})
    monkeypatch.setattr(api, "_get_adapter", lambda model: None)
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 10)
    monkeypatch.setattr(api, "_MULTIPART_SLACK", 0)

    with TestClient(api.app) as client:
        resp = client.post(
            "/api/align",
            files={"audio": ("a.wav", b"0" * 100, "audio/wav"), "transcript": ("t.txt", b"hello")},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"

def test_downloads_round_trip_against_examples() -> None:
    """The download artifacts are byte-identical to the committed examples.

    Regression for moving downloads from embedded response strings to
    format_* + GET /api/download: format_vtt/format_srt must reproduce the
    exact bytes the committed examples carry (they were generated by the
    pipeline on the bundled sample), and write_* (the CLI path) must agree
    with format_* (the API path). Requires the sample transcription, which
    is diskcached (a cache miss would run faster-whisper).
    """
    _, result = api._run_pipeline(api.SAMPLE_AUDIO, api.SAMPLE_TRANSCRIPT, "base", False)
    vtt = format_vtt(result.cues)
    srt = format_srt(result.cues)

    vtt_example = (api.REPO_ROOT / "examples" / "sample_output.vtt").read_text(encoding="utf-8")
    srt_example = (api.REPO_ROOT / "examples" / "sample_output.srt").read_text(encoding="utf-8")
    assert vtt == vtt_example
    assert srt == srt_example

    # write_* (used by the CLI/benchmarks) and format_* (used by the API)
    # must emit identical bytes.
    tmp = api.REPO_ROOT / ".cache"
    tmp.mkdir(exist_ok=True)
    write_vtt(result.cues, tmp / "roundtrip.vtt")
    write_srt(result.cues, tmp / "roundtrip.srt")
    assert (tmp / "roundtrip.vtt").read_text(encoding="utf-8") == vtt
    assert (tmp / "roundtrip.srt").read_text(encoding="utf-8") == srt
    (tmp / "roundtrip.vtt").unlink()
    (tmp / "roundtrip.srt").unlink()


def test_download_endpoint_serves_stored_artifacts(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/download/{audio_id}/{fmt} serves the stored artifacts, and
    unknown formats 404 with the machine-readable code."""
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(api, "_audio_registry", {})
    monkeypatch.setattr(api, "_downloads", {})
    monkeypatch.setattr(api, "_sample_payload", None)
    monkeypatch.setattr(api, "_run_pipeline", lambda *a, **k: _fake_pipeline_result())
    monkeypatch.setattr(api, "_get_adapter", lambda model: None)
    _advance_clock(monkeypatch)

    with TestClient(api.app) as client:
        sample = client.get("/api/sample")
        assert sample.status_code == 200
        audio_id = sample.json()["audio_id"]

        cue = _fake_pipeline_result()[1].cues[0]
        got = client.get(f"/api/download/{audio_id}/vtt")
        assert got.status_code == 200
        assert got.text == format_vtt([cue])

        bad = client.get(f"/api/download/{audio_id}/nope")
        assert bad.status_code == 404
        assert bad.json()["detail"]["code"] == "DOWNLOAD_NOT_FOUND"