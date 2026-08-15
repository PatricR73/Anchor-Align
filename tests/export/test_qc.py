"""S8 — QC report: every S5 constraint checked against produced cues, plus
per-cue confidence JSON derived from Cue.word_span into an AlignedWord list.
"""

from __future__ import annotations

import json

from anchor_align.export.qc import qc_report, write_confidence_json
from anchor_align.models import AlignedWord, Cue, EditedToken, MatchType, QCCode


def _word(i: int, start: float, end: float, confidence: float = 0.9) -> AlignedWord:
    token = EditedToken(text=f"w{i}", index=i, char_offset=0, sentence_id=0, is_sentence_end=False)
    return AlignedWord(token=token, start=start, end=end, match_type=MatchType.EXACT, confidence=confidence)


def test_clean_cue_produces_no_issues():
    cue = Cue(index=1, start=1.0, end=4.0, lines=["A short line."], word_span=(0, 1))
    assert qc_report([cue]) == []


def test_too_many_lines_flagged():
    cue = Cue(index=1, start=1.0, end=4.0, lines=["one", "two", "three"], word_span=(0, 1))
    issues = qc_report([cue])
    assert any(i.code == QCCode.TOO_MANY_LINES and i.cue_index == 1 for i in issues)


def test_line_too_long_flagged():
    cue = Cue(index=1, start=1.0, end=4.0, lines=["x" * 43], word_span=(0, 1))
    issues = qc_report([cue])
    assert any(i.code == QCCode.LINE_TOO_LONG for i in issues)


def test_line_at_exactly_the_limit_is_not_flagged():
    cue = Cue(index=1, start=1.0, end=4.0, lines=["x" * 42], word_span=(0, 1))
    issues = qc_report([cue])
    assert not any(i.code == QCCode.LINE_TOO_LONG for i in issues)


def test_cue_too_short_flagged():
    cue = Cue(index=1, start=1.0, end=1.5, lines=["hi"], word_span=(0, 1))
    issues = qc_report([cue])
    assert any(i.code == QCCode.CUE_TOO_SHORT for i in issues)


def test_cue_too_long_flagged():
    cue = Cue(index=1, start=1.0, end=10.0, lines=["hi"], word_span=(0, 1))
    issues = qc_report([cue])
    assert any(i.code == QCCode.CUE_TOO_LONG for i in issues)


def test_cps_exceeded_flagged():
    # 40 chars in 1 second = 40 cps > 21 max.
    cue = Cue(index=1, start=1.0, end=2.0, lines=["x" * 40], word_span=(0, 1))
    issues = qc_report([cue])
    assert any(i.code == QCCode.CPS_EXCEEDED for i in issues)


def test_overlap_flagged():
    a = Cue(index=1, start=1.0, end=4.0, lines=["a"], word_span=(0, 1))
    b = Cue(index=2, start=3.0, end=6.0, lines=["b"], word_span=(1, 2))  # starts before a ends
    issues = qc_report([a, b])
    assert any(i.code == QCCode.OVERLAP and i.cue_index == 2 for i in issues)


def test_adjacent_non_overlapping_cues_not_flagged():
    a = Cue(index=1, start=1.0, end=4.0, lines=["a"], word_span=(0, 1))
    b = Cue(index=2, start=4.0, end=7.0, lines=["b"], word_span=(1, 2))  # starts exactly when a ends
    issues = qc_report([a, b])
    assert not any(i.code == QCCode.OVERLAP for i in issues)


def test_confidence_json_derives_stats_from_word_span(tmp_path):
    words = [_word(0, 0.0, 1.0, 0.8), _word(1, 1.0, 2.0, 1.0), _word(2, 2.0, 3.0, 0.5)]
    cue = Cue(index=1, start=0.0, end=2.0, lines=["a b"], word_span=(0, 2))  # covers words 0,1 only
    out = write_confidence_json([cue], words, tmp_path / "conf.json")
    report = json.loads(out.read_text())
    assert len(report) == 1
    assert report[0]["cue_index"] == 1
    assert report[0]["mean_confidence"] == 0.9  # mean(0.8, 1.0)
    assert report[0]["min_confidence"] == 0.8
    assert report[0]["word_count"] == 2


def test_confidence_json_handles_empty_word_span(tmp_path):
    cue = Cue(index=1, start=0.0, end=2.0, lines=["a"], word_span=(0, 0))
    out = write_confidence_json([cue], [], tmp_path / "conf.json")
    report = json.loads(out.read_text())
    assert report[0]["mean_confidence"] is None
    assert report[0]["word_count"] == 0
