"""S2 steps 6-7 — contractions and numerals. Both are segment-node, not
token splits: char_span/source_indices/normal stay untouched, only
`variants` gains alternate readings. These are the two steps that change
*meaning* of a token count across streams — see the S1<->S3 note these
tests exist to back up.
"""

from __future__ import annotations

from anchor_align.normalize.normalizer import (
    assert_span_invariant,
    casefold_and_ascii_fold,
    expand_contractions,
    expand_numerals,
    extract_trailing_punct,
    fold_unicode,
    normalize_tokens,
)

# --------------------------------------------------------------------------
# Contractions
# --------------------------------------------------------------------------


def test_known_contraction_gets_expanded_variant():
    tokens = normalize_tokens("Don't stop")
    tokens = extract_trailing_punct(tokens)
    tokens = casefold_and_ascii_fold(tokens, ascii_fold=False)
    tokens = expand_contractions(tokens)
    assert tokens[0].normal == "don't"
    assert ("do", "not") in tokens[0].variants


def test_non_contraction_token_gets_no_variants():
    tokens = normalize_tokens("hello world")
    tokens = expand_contractions(tokens)
    assert all(t.variants == () for t in tokens)


def test_contraction_preserves_surface_and_span():
    text = "Don't stop"
    tokens = normalize_tokens(text)
    expanded = expand_contractions(extract_trailing_punct(casefold_and_ascii_fold(tokens, ascii_fold=False)))
    assert expanded[0].surface == "Don't"
    assert expanded[0].char_span == (0, 5)


def test_all_known_contractions_expand():
    tokens = normalize_tokens("don't can't it's won't")
    tokens = casefold_and_ascii_fold(tokens, ascii_fold=False)
    tokens = expand_contractions(tokens)
    expansions = [t.variants[0] if t.variants else None for t in tokens]
    assert expansions == [("do", "not"), ("can", "not"), ("it", "is"), ("will", "not")]


def test_expand_contractions_does_not_duplicate_existing_variant():
    tokens = normalize_tokens("don't")
    tokens = casefold_and_ascii_fold(tokens, ascii_fold=False)
    tokens = [tokens[0].model_copy(update={"variants": (("do", "not"),)})]
    result = expand_contractions(tokens)
    assert result[0].variants == (("do", "not"),)


# --------------------------------------------------------------------------
# Numerals
# --------------------------------------------------------------------------


def test_plain_number_gets_cardinal_reading():
    tokens = normalize_tokens("35")
    tokens = expand_numerals(tokens)
    assert ("thirty", "five") in tokens[0].variants
    assert tokens[0].normal == "35"  # canonical stays digit form


def test_percent_number_appends_percent_word():
    tokens = normalize_tokens("20%")
    tokens = expand_numerals(tokens)
    assert ("twenty", "percent") in tokens[0].variants


def test_year_range_number_gets_both_cardinal_and_year_reading():
    tokens = normalize_tokens("2024")
    tokens = expand_numerals(tokens)
    variants = tokens[0].variants
    assert ("two", "thousand", "twenty", "four") in variants
    assert ("twenty", "twenty", "four") in variants
    assert len(variants) == 2


def test_round_year_does_not_duplicate_identical_readings():
    # num2words(2000) == num2words(2000, to="year") == "two thousand"
    tokens = normalize_tokens("2000")
    tokens = expand_numerals(tokens)
    assert tokens[0].variants == (("two", "thousand"),)


def test_non_numeral_token_gets_no_variants():
    tokens = normalize_tokens("hello")
    tokens = expand_numerals(tokens)
    assert tokens[0].variants == ()


def test_number_outside_year_range_gets_only_cardinal_reading():
    tokens = normalize_tokens("50000")
    tokens = expand_numerals(tokens)
    assert len(tokens[0].variants) == 1


def test_numeral_preserves_surface_and_span():
    text = "About 2024 now"
    tokens = normalize_tokens(text)
    expanded = expand_numerals(tokens)
    assert expanded[1].surface == "2024"
    assert expanded[1].char_span == tokens[1].char_span


def test_hyphenated_and_and_forms_split_into_separate_words():
    tokens = normalize_tokens("2024")
    tokens = expand_numerals(tokens)
    # "two thousand and twenty-four" must become 4 separate words, not
    # "twenty-four" as one hyphenated chunk or "and" left dangling.
    cardinal = next(v for v in tokens[0].variants if len(v) == 4)
    assert cardinal == ("two", "thousand", "twenty", "four")
    assert "and" not in cardinal


# --------------------------------------------------------------------------
# Full pipeline through all 7 steps
# --------------------------------------------------------------------------


def test_full_pipeline_preserves_span_invariant():
    text = "Șerban said, HELLO don't 2024 20%!"
    tokens = normalize_tokens(text)
    tokens = fold_unicode(tokens)
    tokens = extract_trailing_punct(tokens)
    tokens = casefold_and_ascii_fold(tokens)
    tokens = expand_contractions(tokens)
    tokens = expand_numerals(tokens)
    assert_span_invariant(text, tokens)
    for t in tokens:
        start, end = t.char_span
        assert text[start:end] == t.surface


def test_full_pipeline_end_to_end_multi_token_expansion_is_available_for_s3():
    """The property S3 needs: a single edited token ('20%') carries a
    variant reading that is itself a MULTI-WORD sequence, so S3's alignment
    can match it against two separate gold words ('twenty', 'percent')
    without any information loss. This is the exact case flagged as
    untested risk before these two steps existed — a 1:1 pipeline can't
    exercise this at all."""
    tokens = normalize_tokens("The rate was 20% higher")
    tokens = casefold_and_ascii_fold(tokens, ascii_fold=False)
    tokens = expand_numerals(tokens)
    numeral_token = next(t for t in tokens if t.surface == "20%")
    assert numeral_token.variants == (("twenty", "percent"),)
    # source_indices still singleton — this is one edited token wide, its
    # multi-word reading lives entirely in `variants`, not in a token split.
    assert len(numeral_token.source_indices) == 1
