"""S2 steps 2-4: cedilla/NFC folding, punctuation-as-attribute, casefold +
ASCII fold. Each step's own test calls assert_span_invariant again on its
output, per normalizer.py's own instruction — a property proven at step 1
must be reverified at every later step, not assumed to survive.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from anchor_align.normalize.normalizer import (
    assert_span_invariant,
    casefold_and_ascii_fold,
    extract_trailing_punct,
    fold_unicode,
    normalize_tokens,
)

# --------------------------------------------------------------------------
# Step 2: cedilla/NFC folding
# --------------------------------------------------------------------------


def test_cedilla_forms_fold_to_comma_below():
    cedilla_text = "şi ţara"  # şi ţara (legacy cedilla forms)
    comma_text = "și țara"  # și țara (modern comma-below forms)

    cedilla_tokens = fold_unicode(normalize_tokens(cedilla_text))
    comma_tokens = fold_unicode(normalize_tokens(comma_text))

    assert [t.normal for t in cedilla_tokens] == [t.normal for t in comma_tokens]


def test_fold_unicode_preserves_surface_and_span():
    text = "şi ţara"
    tokens = normalize_tokens(text)
    folded = fold_unicode(tokens)
    assert [t.surface for t in folded] == [t.surface for t in tokens]
    assert [t.char_span for t in folded] == [t.char_span for t in tokens]
    # surface still un-folded (original preserved for display)
    assert folded[0].surface == "şi"
    assert folded[0].normal == "și"


def test_fold_unicode_is_idempotent():
    text = "și țara ordinary text"
    once = fold_unicode(normalize_tokens(text))
    twice = fold_unicode(once)
    assert [t.normal for t in once] == [t.normal for t in twice]


# --------------------------------------------------------------------------
# Step 3: punctuation as an attribute
# --------------------------------------------------------------------------


def test_trailing_punct_extracted_from_normal():
    tokens = extract_trailing_punct(normalize_tokens("Don't stop, please."))
    assert [t.normal for t in tokens] == ["Don't", "stop", "please"]
    assert [t.trailing_punct for t in tokens] == ["", ",", "."]


def test_apostrophe_inside_word_is_not_extracted():
    tokens = extract_trailing_punct(normalize_tokens("Don't"))
    assert tokens[0].normal == "Don't"
    assert tokens[0].trailing_punct == ""


def test_surface_and_span_unchanged_by_punct_extraction():
    text = "hello, world!"
    tokens = normalize_tokens(text)
    extracted = extract_trailing_punct(tokens)
    assert [t.surface for t in extracted] == [t.surface for t in tokens]
    assert [t.char_span for t in extracted] == [t.char_span for t in tokens]


def test_no_trailing_punct_leaves_normal_untouched():
    tokens = extract_trailing_punct(normalize_tokens("hello world"))
    assert [t.normal for t in tokens] == ["hello", "world"]
    assert all(t.trailing_punct == "" for t in tokens)


# --------------------------------------------------------------------------
# Step 4: casefold + ASCII fold
# --------------------------------------------------------------------------


def test_casefold_lowercases():
    tokens = casefold_and_ascii_fold(normalize_tokens("HELLO World"))
    assert [t.normal for t in tokens] == ["hello", "world"]


def test_ascii_fold_strips_romanian_diacritics_by_default():
    tokens = casefold_and_ascii_fold(fold_unicode(normalize_tokens("Șerban și țara")))
    assert [t.normal for t in tokens] == ["serban", "si", "tara"]


def test_ascii_fold_disabled_keeps_diacritics():
    tokens = casefold_and_ascii_fold(
        fold_unicode(normalize_tokens("Șerban și țara")), ascii_fold=False
    )
    assert [t.normal for t in tokens] == ["șerban", "și", "țara"]


def test_casefold_and_ascii_fold_preserves_surface_and_span():
    text = "HELLO Șerban"
    tokens = normalize_tokens(text)
    folded = casefold_and_ascii_fold(tokens)
    assert [t.surface for t in folded] == [t.surface for t in tokens]
    assert [t.char_span for t in folded] == [t.char_span for t in tokens]


# --------------------------------------------------------------------------
# Full pipeline (steps 1-4) property + span invariant re-checked at each step
# --------------------------------------------------------------------------

_TEXT_ALPHABET = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "ăâîșțĂÂÎȘȚ"
    "ŞşŢţ"  # cedilla forms too
    "0123456789"
    " \t\n"
    ".,!?;:'\"-—()[]%$"
)
_text_strategy = st.text(alphabet=_TEXT_ALPHABET, max_size=200)


@given(text=_text_strategy)
def test_pipeline_through_step_4_preserves_span_invariant(text: str):
    tokens = normalize_tokens(text)
    tokens = fold_unicode(tokens)
    tokens = extract_trailing_punct(tokens)
    tokens = casefold_and_ascii_fold(tokens)
    # surface/char_span must be exactly what step 1 produced — every step
    # since only ever touches normal/trailing_punct.
    assert_span_invariant(text, tokens)
    for t in tokens:
        start, end = t.char_span
        assert text[start:end] == t.surface
