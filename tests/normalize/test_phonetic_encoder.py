"""S2 step 5 — phonetic encoders. NullEncoder disables phonetic matching;
DoubleMetaphoneEncoder provides English-tuned (primary, alternate) keys."""

from __future__ import annotations

from anchor_align.normalize.normalizer import (
    DoubleMetaphoneEncoder,
    NullEncoder,
    apply_phonetic_encoder,
    assert_span_invariant,
    casefold_and_ascii_fold,
    extract_trailing_punct,
    fold_unicode,
    normalize_tokens,
)


def test_null_encoder_returns_zero_keys():
    encoder = NullEncoder()
    assert encoder.encode("hello") == ()
    assert encoder.encode("") == ()


def test_double_metaphone_encoder_returns_keys():
    encoder = DoubleMetaphoneEncoder()
    assert encoder.encode("hello") == ("HL",)
    assert encoder.encode("frayed") == ("FRT",)


def test_double_metaphone_encoder_empty_token_has_no_keys():
    assert DoubleMetaphoneEncoder().encode("") == ()
    # pure digits have no phonetic content — "no key", not a mismatch
    assert DoubleMetaphoneEncoder().encode("2024") == ()


def test_double_metaphone_encoder_alternate_keys_preserved():
    encoder = DoubleMetaphoneEncoder()
    keys = encoder.encode("the")
    assert len(keys) == 2  # primary + alternate differ


def test_homophones_share_a_key():
    a = DoubleMetaphoneEncoder().encode("frayed")
    b = DoubleMetaphoneEncoder().encode("frade")
    assert set(a) & set(b)


def test_apply_phonetic_encoder_populates_keys():
    tokens = normalize_tokens("hello world")
    encoded = apply_phonetic_encoder(tokens, NullEncoder())
    assert all(t.keys == () for t in encoded)


def test_apply_phonetic_encoder_preserves_surface_and_span():
    text = "hello world"
    tokens = normalize_tokens(text)
    encoded = apply_phonetic_encoder(tokens, NullEncoder())
    assert [t.surface for t in encoded] == [t.surface for t in tokens]
    assert [t.char_span for t in encoded] == [t.char_span for t in tokens]


class _UppercaseEchoEncoder:
    """A trivial non-null PhoneticEncoder for testing apply_phonetic_encoder
    against something that actually returns keys, without depending on a
    real phonetic algorithm."""

    def encode(self, token: str) -> tuple[str, ...]:
        return (token.upper(),) if token else ()


def test_apply_phonetic_encoder_runs_on_normal_not_surface():
    """Phonetic encoding runs after fold/casefold — on `normal`, not
    `surface` — so it's insensitive to the same casing/Unicode variance
    exact matching already is by this point."""
    tokens = normalize_tokens("HELLO")
    tokens = fold_unicode(tokens)
    tokens = extract_trailing_punct(tokens)
    tokens = casefold_and_ascii_fold(tokens)  # normal is now "hello"
    encoded = apply_phonetic_encoder(tokens, _UppercaseEchoEncoder())
    assert encoded[0].keys == ("HELLO",)  # encoder saw "hello", echoed upper
    assert encoded[0].surface == "HELLO"  # surface untouched


def test_full_pipeline_through_step_5_preserves_span_invariant():
    text = "Șerban said, HELLO world!"
    tokens = normalize_tokens(text)
    tokens = fold_unicode(tokens)
    tokens = extract_trailing_punct(tokens)
    tokens = casefold_and_ascii_fold(tokens)
    tokens = apply_phonetic_encoder(tokens, NullEncoder())
    assert_span_invariant(text, tokens)
    for t in tokens:
        start, end = t.char_span
        assert text[start:end] == t.surface
