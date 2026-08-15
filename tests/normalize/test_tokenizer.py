"""S2 step 1 — tokenizer + span invariant.

Get this green on raw, un-normalized text before any transform exists:
every later step in normalizer.py inherits this property instead of having
to re-derive it, and a span bug shows up at the transform that caused it
rather than three steps downstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from anchor_align.normalize.normalizer import assert_span_invariant, normalize_tokens

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "data" / "sample"


def _check_invariant(text: str, tokens) -> None:
    # normalize_tokens already calls this internally; calling it again here
    # is the point — assert_span_invariant is meant to be reusable by every
    # later transform's own tests, so exercise it as an external caller too.
    assert_span_invariant(text, tokens)


# ---------------------------------------------------------------------
# Property test over arbitrary text
# ---------------------------------------------------------------------

# Printable text plus the separators a real transcript will contain:
# ASCII, Romanian diacritics, common punctuation, and whitespace variants.
_TEXT_ALPHABET = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "ăâîșțĂÂÎȘȚ"
    "0123456789"
    " \t\n"
    ".,!?;:'\"-—()[]%$"
)

_text_strategy = st.text(alphabet=_TEXT_ALPHABET, max_size=200)


@given(text=_text_strategy)
def test_span_invariant_holds_on_arbitrary_text(text: str):
    tokens = normalize_tokens(text)
    _check_invariant(text, tokens)

    # spans monotonic and non-overlapping
    ends = [t.char_span[1] for t in tokens]
    starts = [t.char_span[0] for t in tokens]
    assert starts == sorted(starts)
    for i in range(len(tokens) - 1):
        assert ends[i] <= starts[i + 1]

    # every source_indices is this token's own ordinal position
    for i, t in enumerate(tokens):
        assert t.source_indices == (i,)

    # no transform has run yet: normal == surface
    assert all(t.normal == t.surface for t in tokens)


# ---------------------------------------------------------------------
# Real(-ish) sample text
# ---------------------------------------------------------------------


@pytest.mark.parametrize("sample_path", sorted(SAMPLE_DIR.glob("*.txt")))
def test_span_invariant_holds_on_sample_transcripts(sample_path: Path):
    text = sample_path.read_text(encoding="utf-8")
    tokens = normalize_tokens(text)
    assert tokens, f"{sample_path} tokenized to zero tokens"
    _check_invariant(text, tokens)
    # every token's surface matches exactly what its span slices out of the source
    for t in tokens:
        start, end = t.char_span
        assert text[start:end] == t.surface


def test_sample_dir_is_not_empty():
    # Guards against the property test above silently collecting zero cases
    # if the sample directory is ever emptied.
    assert list(SAMPLE_DIR.glob("*.txt")), "data/sample has no .txt fixtures"


# ---------------------------------------------------------------------
# Focused unit tests
# ---------------------------------------------------------------------


def test_empty_text_yields_no_tokens():
    assert normalize_tokens("") == []


def test_whitespace_only_text_yields_no_tokens():
    assert normalize_tokens("   \n\t  ") == []


def test_single_word():
    tokens = normalize_tokens("hello")
    assert len(tokens) == 1
    assert tokens[0].surface == "hello"
    assert tokens[0].char_span == (0, 5)


def test_multiple_spaces_between_words_collapse_to_one_gap():
    tokens = normalize_tokens("hello    world")
    assert [t.surface for t in tokens] == ["hello", "world"]
    assert tokens[0].char_span == (0, 5)
    assert tokens[1].char_span == (9, 14)


def test_leading_and_trailing_whitespace_is_not_a_token():
    tokens = normalize_tokens("  hi  ")
    assert [t.surface for t in tokens] == ["hi"]
    assert tokens[0].char_span == (2, 4)


def test_punctuation_stays_attached_to_the_token_at_this_step():
    tokens = normalize_tokens("Don't stop, please.")
    assert [t.surface for t in tokens] == ["Don't", "stop,", "please."]
    for t in tokens:
        assert t.trailing_punct == ""  # not split out yet — that's a later step


def test_newlines_are_gaps_like_any_other_whitespace():
    tokens = normalize_tokens("line one\nline two")
    assert [t.surface for t in tokens] == ["line", "one", "line", "two"]


def test_overlapping_spans_are_rejected():
    text = "hello world"
    tokens = normalize_tokens(text)
    # Force an overlap: second token's span starts before the first ends.
    tampered = [
        tokens[0],
        tokens[1].model_copy(update={"char_span": (3, tokens[1].char_span[1])}),
    ]
    with pytest.raises(ValueError, match="overlaps or goes backwards"):
        assert_span_invariant(text, tampered)


def test_gap_with_a_dropped_word_is_rejected():
    text = "hello secret world"
    tokens = normalize_tokens(text)
    # Drop the middle token entirely — its text becomes an unexplained gap.
    tampered = [tokens[0], tokens[2]]
    with pytest.raises(ValueError, match="not whitespace/punctuation"):
        assert_span_invariant(text, tampered)
