"""S2 — normalization.

Brings both streams (STT output, edited transcript) to a comparable form
without destroying the original: lowercase, punctuation as data, a numeral
direction, a phonetic key per word via a pluggable `PhoneticEncoder`
(interfaces.py). Every word keeps its original surface for display; `normal`
is the comparison form, `char_span` always reconstructs the source.

Numeral direction is one-way and load-bearing: normalization only expands
digits to words (via num2words), never the reverse. The words->digits
direction exists only in corrupt/corruptor.py, simulating an editor's
stylistic choice; violating this invariant breaks
`normalize(normalize(x)) == normalize(x)`.

A numeral span stays ONE NormalizedToken (one `char_span`, atomic), with
every plausible reading stored on it — `normal` for the canonical one,
`variants` for the rest. This keeps S3's DP over a flat sequence (not a
DAG) while S3 still picks which reading scores best; it does not derive
them.

Build order is pinned, least branching complexity first: tokenizer + span
invariant, Unicode folding, punctuation-as-attribute, casefold + ASCII
fold, phonetic encoders, contractions, numerals last. Every step rewrites
only `normal`/`trailing_punct`/`keys`/`variants`; none may touch
`char_span` or `surface`.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from typing import cast

import num2words
from metaphone import doublemetaphone

from anchor_align.contractions import CONTRACTIONS
from anchor_align.interfaces import PhoneticEncoder
from anchor_align.models import NormalizedToken

# Step 1 only: whitespace-delimited splitting. Punctuation stays attached to
# the token it's adjacent to until the punctuation-as-attribute step.
_TOKEN_RE = re.compile(r"\S+")


def normalize_tokens(text: str) -> list[NormalizedToken]:
    """Tokenizer + span invariant — the first step in the build order.
    `normal` starts out equal to `surface`: no transform has run yet."""
    spans = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    tokens = [
        NormalizedToken(
            surface=text[start:end],
            normal=text[start:end],
            char_span=(start, end),
            source_indices=(i,),
        )
        for i, (start, end) in enumerate(spans)
    ]
    assert_span_invariant(text, tokens)
    return tokens


def assert_span_invariant(text: str, tokens: list[NormalizedToken]) -> None:
    """The property every transform must preserve: spans are monotonic and
    non-overlapping, and spans plus gaps reconstruct `text` exactly with
    every gap whitespace/punctuation only — never a silently-dropped word."""
    prev_end = 0
    reconstructed: list[str] = []
    for token in tokens:
        start, end = token.char_span
        if start < prev_end:
            raise ValueError(
                f"char_span overlaps or goes backwards: prev_end={prev_end}, span=({start}, {end})"
            )
        gap = text[prev_end:start]
        if not _is_whitespace_or_punct(gap):
            raise ValueError(f"gap {gap!r} before span ({start}, {end}) is not whitespace/punctuation")
        reconstructed.append(gap)
        reconstructed.append(text[start:end])
        prev_end = end

    trailing_gap = text[prev_end:]
    if not _is_whitespace_or_punct(trailing_gap):
        raise ValueError(f"trailing gap {trailing_gap!r} is not whitespace/punctuation")
    reconstructed.append(trailing_gap)

    if "".join(reconstructed) != text:
        raise ValueError("token spans plus gaps do not reconstruct the source text exactly")


def _is_whitespace_or_punct(fragment: str) -> bool:
    return all(ch.isspace() or unicodedata.category(ch).startswith("P") for ch in fragment)


# --------------------------------------------------------------------------
# Step 2: NFC + cedilla-comma folding
# --------------------------------------------------------------------------

# Romanian s/t have two Unicode encodings in the wild: comma-below
# (U+0218/9, U+021A/B — the correct modern form) and cedilla (U+015E/F,
# U+0162/3 — a legacy Turkish-keyboard-derived form). Both must compare
# equal, or two transcripts of the same speech differing only in font
# would never match. Folds cedilla to comma-below; NFC composes decomposed
# accents so composed vs. decomposed forms also compare equal.
_CEDILLA_TO_COMMA = str.maketrans(
    {
        "Ş": "Ș",  # Ş -> Ș
        "ş": "ș",  # ş -> ș
        "Ţ": "Ț",  # Ţ -> Ț
        "ţ": "ț",  # ţ -> ț
    }
)


def fold_unicode(tokens: list[NormalizedToken]) -> list[NormalizedToken]:
    """Cedilla-fold then NFC-normalize `normal`; `surface`/`char_span` stay
    untouched."""
    return [
        t.model_copy(
            update={"normal": unicodedata.normalize("NFC", t.normal.translate(_CEDILLA_TO_COMMA))}
        )
        for t in tokens
    ]


# --------------------------------------------------------------------------
# Step 3: punctuation as an attribute
# --------------------------------------------------------------------------


def extract_trailing_punct(tokens: list[NormalizedToken]) -> list[NormalizedToken]:
    """Move trailing punctuation out of `normal` and into `trailing_punct`
    as data rather than deleting it. Only TRAILING punctuation: an
    apostrophe inside "don't" must survive into the contraction step, and a
    token that starts with punctuation is a tokenizer-quality question, not
    this step's job."""
    result = []
    for t in tokens:
        normal = t.normal
        end = len(normal)
        while end > 0 and unicodedata.category(normal[end - 1]).startswith("P"):
            end -= 1
        result.append(t.model_copy(update={"normal": normal[:end], "trailing_punct": normal[end:]}))
    return result


# --------------------------------------------------------------------------
# Step 4: casefold + ASCII fold
# --------------------------------------------------------------------------

# Comma-below forms only: fold_unicode (step 2) always runs first, so
# cedilla forms are gone by the time this step sees a token.
_ROMANIAN_ASCII_FOLD = str.maketrans(
    {"ă": "a", "â": "a", "î": "i", "ș": "s", "ț": "t", "Ă": "A", "Â": "A", "Î": "I", "Ș": "S", "Ț": "T"}
)


def casefold_and_ascii_fold(tokens: list[NormalizedToken], *, ascii_fold: bool = True) -> list[NormalizedToken]:
    """Casefold `normal` (Unicode casefold, not `.lower()` — correct for
    German ß-style expansions). ASCII-fold Romanian diacritics by default:
    STT engines commonly drop diacritics even when the transcript keeps
    them, so the comparison form must be robust to either side losing
    them. `ascii_fold=False` is for streams verified diacritic-consistent.
    """
    result = []
    for t in tokens:
        normal = t.normal.casefold()
        if ascii_fold:
            normal = normal.translate(_ROMANIAN_ASCII_FOLD)
        result.append(t.model_copy(update={"normal": normal}))
    return result


# --------------------------------------------------------------------------
# Step 5: phonetic encoders
# --------------------------------------------------------------------------


class NullEncoder:
    """No phonetic matching — every token gets zero keys. Implements
    `PhoneticEncoder`; the opt-out strategy for content where phonetic
    matching would add noise rather than recall."""

    def encode(self, token: str) -> tuple[str, ...]:
        return ()


@cache
def _double_metaphone(token: str) -> tuple[str, str]:
    # metaphone has no type stubs; the package contract is a 2-tuple.
    return cast(tuple[str, str], doublemetaphone(token))


class DoubleMetaphoneEncoder:
    """English/Germanic-tuned phonetic keys via the `metaphone` package
    (Double Metaphone, primary + alternate key). Implements
    `PhoneticEncoder`.

    Runs on the ASCII-folded `normal` form, so Romanian diacritics are gone
    before encoding. Unvalidated on Romanian text — Double Metaphone's
    English/Germanic tuning may be wrong for it; a phonemic encoder can be
    benchmarked against this one via the `PhoneticEncoder` protocol.
    """

    def encode(self, token: str) -> tuple[str, ...]:
        if not token:
            return ()
        primary, alternate = _double_metaphone(token)
        return tuple(dict.fromkeys(key for key in (primary, alternate) if key))


def apply_phonetic_encoder(tokens: list[NormalizedToken], encoder: PhoneticEncoder) -> list[NormalizedToken]:
    """Populate `keys` from the configured `PhoneticEncoder`, run over each
    token's `normal` form — phonetic matching should be insensitive to
    casing/encoding variance the same way exact matching is by this point."""
    return [t.model_copy(update={"keys": encoder.encode(t.normal)}) for t in tokens]


# --------------------------------------------------------------------------
# Step 6: contractions
# --------------------------------------------------------------------------


def expand_contractions(tokens: list[NormalizedToken]) -> list[NormalizedToken]:
    """For a known contraction, add the expanded two-word reading as a
    `variants` entry — segment-node, not a token merge: `char_span`/
    `source_indices`/`normal` stay untouched, S3 picks whichever reading
    scores best.

    Only the contraction -> expansion direction is handled (one input
    token -> a two-word reading). The reverse — two separate input tokens
    that should match a single contraction on the other side — is a
    token-MERGE problem, out of scope for segment-node.
    """
    result = []
    for t in tokens:
        expansion = CONTRACTIONS.get(t.normal)
        if expansion is None or expansion in t.variants:
            result.append(t)
        else:
            result.append(t.model_copy(update={"variants": t.variants + (expansion,)}))
    return result


# --------------------------------------------------------------------------
# Step 7 (last, per the pinned build order — real branching complexity):
# numerals
# --------------------------------------------------------------------------

_NUMERAL_RE = re.compile(r"^(\d+)%?$")
_YEAR_RANGE = range(1000, 3000)


def _split_num2words(text: str) -> tuple[str, ...]:
    # num2words emits "and" as a cardinal-grammar connector ("two thousand
    # and twenty-four") and hyphenates compounds ("twenty-four") — neither
    # is how a real speaker's transcript renders separate word tokens.
    return tuple(text.replace(" and ", " ").replace("-", " ").split())


def _numeral_readings(n: int) -> list[tuple[str, ...]]:
    """Every plausible word-sequence reading for a bare number, most
    specific/common first. A year in [1000, 3000) gets BOTH a cardinal
    reading and a year-style reading as separate variants — real speech
    uses both, and picking one here would be the premature commitment
    segment-node exists to avoid."""
    readings = [_split_num2words(num2words.num2words(n))]
    if n in _YEAR_RANGE:
        year_reading = _split_num2words(num2words.num2words(n, to="year"))
        if year_reading not in readings:
            readings.append(year_reading)
    return readings


def expand_numerals(tokens: list[NormalizedToken]) -> list[NormalizedToken]:
    """For a token whose `normal` is purely digits (optionally with a
    trailing '%'), add one or more word-sequence readings as `variants` —
    digits -> words only, never the reverse (see the module docstring).

    The '%' sign is checked in BOTH `normal` and `trailing_punct`: step 3
    moves it out of `normal` in the normal build order, but this function
    must still work if numerals ever run before punctuation extraction.
    """
    result = []
    for t in tokens:
        m = _NUMERAL_RE.match(t.normal)
        if m is None:
            result.append(t)
            continue
        n = int(m.group(1))
        has_percent = t.normal.endswith("%") or t.trailing_punct == "%"
        new_variants = list(t.variants)
        for reading in _numeral_readings(n):
            if has_percent:
                reading = (*reading, "percent")
            if reading not in new_variants:
                new_variants.append(reading)
        result.append(t.model_copy(update={"variants": tuple(new_variants)}))
    return result
