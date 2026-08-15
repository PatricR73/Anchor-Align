"""S1 — synthetic corpus generator tests.

Not testing realism (the corpus generator explicitly does not claim
calibration — see corpus.py's module docstring) — testing the two
properties that actually matter for the statistical-power problem this
module exists to fix: real variation in document length and opportunity
density, and a deterministic, reproducible corpus given a seed.
"""

from __future__ import annotations

import statistics
from itertools import pairwise

from anchor_align.corrupt.corpus import generate_corpus
from anchor_align.corrupt.corruptor import (
    ASR_NAME_CORRECTIONS,
    CONTRACTIONS,
    FILLER_WORDS,
)


def test_deterministic_given_seed():
    a = generate_corpus(10, seed=1)
    b = generate_corpus(10, seed=1)
    assert a == b


def test_different_seed_diverges():
    a = generate_corpus(10, seed=1)
    b = generate_corpus(10, seed=2)
    assert a != b


def test_doc_ids_are_unique():
    corpus = generate_corpus(20, seed=1)
    ids = [doc_id for doc_id, _ in corpus]
    assert len(ids) == len(set(ids))


def test_document_lengths_vary():
    corpus = generate_corpus(20, seed=1)
    lengths = [len(words) for _, words in corpus]
    assert len(set(lengths)) > 1, "every document has the same length — no length variation"
    assert statistics.stdev(lengths) > 0


def test_filler_opportunity_counts_vary_and_exceed_single_fixture():
    """The single hand-written fixture has ~6 filler-word opportunities.
    The point of the corpus is that pooling across many documents gives far
    more total opportunities, and that per-document counts aren't all
    identical (so the corpus isn't just N copies of one density profile)."""
    corpus = generate_corpus(20, seed=1)
    counts = [
        sum(1 for w in words if w.text.strip(",.!?").casefold() in FILLER_WORDS) for _, words in corpus
    ]
    assert sum(counts) > 30, f"only {sum(counts)} total filler opportunities across the corpus"
    assert len(set(counts)) > 1, "every document has the identical filler count"


def test_name_and_contraction_opportunities_exceed_single_fixture():
    corpus = generate_corpus(40, seed=1)
    name_count = sum(
        1 for _, words in corpus for w in words if w.text.casefold() in ASR_NAME_CORRECTIONS
    )
    contraction_count = sum(
        1 for _, words in corpus for w in words if w.text.casefold() in CONTRACTIONS
    )
    # Single fixture has 2 name occurrences and ~5 contractions; the whole
    # point of pooling many documents is having meaningfully more than that.
    assert name_count > 5, f"only {name_count} name-correction opportunities across the corpus"
    assert contraction_count > 20, f"only {contraction_count} contraction opportunities across the corpus"


def test_timing_has_sentence_boundary_pauses():
    """At least some inter-word gaps must be meaningfully larger than the
    baseline word-to-word gap — otherwise this is still purely sequential
    timing with no pause structure, and the corpus doesn't actually fix
    what it claims to fix for a time-weighted metric."""
    corpus = generate_corpus(10, seed=1)
    large_gaps = 0
    for _, words in corpus:
        for a, b in pairwise(words):
            if b.start - a.end > 0.25:
                large_gaps += 1
    assert large_gaps > 5, f"only {large_gaps} gaps > 250ms found across the corpus — no real pause structure"


def test_every_word_is_a_valid_sttword():
    # STTWord's own TimeSpan validator (end >= start, quantized, ge=0)
    # already enforces this at construction — this just confirms
    # generate_corpus doesn't need to be caught constructing anything
    # invalid, across a reasonably large sample.
    corpus = generate_corpus(30, seed=7)
    assert sum(len(words) for _, words in corpus) > 0
