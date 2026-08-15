"""CLI smoke tests: argument handling and an end-to-end run with a stubbed
transcription (no network or model download in unit tests)."""

from __future__ import annotations

from pathlib import Path

from anchor_align.cli import main
from anchor_align.models import STTWord, Transcription


def _fake_transcription() -> Transcription:
    words = []
    t = 0.0
    for text in ["Hello", "world.", "This", "is", "a", "short", "pipeline", "test."]:
        words.append(STTWord(text=text, start=t, end=t + 0.4))
        t += 0.5
    return Transcription(words=words, model_id="fake", audio_duration=t)


def _write_transcript(path: Path) -> None:
    path.write_text("Hello world. This is a short pipeline test.", encoding="utf-8")


def test_missing_audio_returns_1(tmp_path):
    transcript = tmp_path / "t.txt"
    _write_transcript(transcript)
    assert main([str(tmp_path / "missing.mp3"), str(transcript)]) == 1


def test_missing_transcript_returns_1(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    assert main([str(audio), str(tmp_path / "missing.txt")]) == 1


def test_end_to_end_writes_all_outputs(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake audio bytes")
    transcript = tmp_path / "t.txt"
    _write_transcript(transcript)
    out_dir = tmp_path / "out"

    monkeypatch.setattr(
        "anchor_align.cli.cached_transcribe",
        lambda audio_path, name, provider, opts, cache_dir: _fake_transcription(),
    )

    code = main([str(audio), str(transcript), "--out", str(out_dir)])
    assert code == 0
    assert (out_dir / "captions.vtt").exists()
    assert (out_dir / "captions.srt").exists()
    assert (out_dir / "captions.confidence.json").exists()
    vtt_text = (out_dir / "captions.vtt").read_text(encoding="utf-8")
    assert vtt_text.startswith("WEBVTT")
    assert "Hello world." in vtt_text


def test_batch_mode_writes_per_pair_outputs_and_summary(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "a.mp3").write_bytes(b"audio a")
    (in_dir / "a.txt").write_text("Hello world. This is a short pipeline test.", encoding="utf-8")
    (in_dir / "b.mp3").write_bytes(b"audio b")  # no transcript -> skipped
    out_dir = tmp_path / "out"

    monkeypatch.setattr(
        "anchor_align.cli.cached_transcribe",
        lambda audio_path, name, provider, opts, cache_dir: _fake_transcription(),
    )

    code = main(["--batch", str(in_dir), "--out", str(out_dir)])
    assert code == 0
    assert (out_dir / "a.vtt").exists()
    assert (out_dir / "a.srt").exists()
    assert (out_dir / "a.confidence.json").exists()
    assert not (out_dir / "b.vtt").exists()

    summary = (out_dir / "qc_summary.csv").read_text(encoding="utf-8")
    assert "a.mp3" in summary
    assert "cues" in summary.splitlines()[0]  # header row
    assert "b.mp3" not in summary


def test_batch_mode_missing_dir_returns_1(tmp_path):
    assert main(["--batch", str(tmp_path / "nope"), "--out", str(tmp_path / "out")]) == 1


def test_batch_mode_with_no_pairs_returns_1(tmp_path):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "readme.txt").write_text("no audio here", encoding="utf-8")
    assert main(["--batch", str(in_dir), "--out", str(tmp_path / "out")]) == 1


def test_positional_mode_requires_both_files(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    assert main([str(audio)]) == 2  # argparse error
