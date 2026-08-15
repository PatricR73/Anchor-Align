"""S1 tests — corruption generator "done when" checks.

Exact-equality assertions (determinism, structural invariants) are strict
and per-seed. Statistical assertions (measured rate vs. configured rate) are
pooled across several seeds and checked against a binomial-ish tolerance
band computed from the actual opportunity count in the fixture — not a
hand-picked epsilon — since a single ~150-token document gives single-digit
event counts per seed at realistic rates.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import subprocess
import sys
from dataclasses import fields
from itertools import pairwise
from pathlib import Path

import pytest

from anchor_align.corrupt.corruptor import (
    FILLER_WORDS,
    TRANSFORM_ORDER,
    CorruptionConfig,
    _Unit,
    corrupt,
    filler_removal,
    repetition_collapse,
)
from anchor_align.models import EditRelation, STTWord, classify_all

# ---------------------------------------------------------------------
# Fixture: ~150 words, sequential timing, with known corruption targets.
# ---------------------------------------------------------------------

_FIXTURE_TEXT = """
So the project started last spring and honestly it was um a mess at first.
We we spent three weeks just trying to get the the pipeline working end to end.
I don't think anyone on the team expected it to take that long, actually.
The the F B I released a report about it, which uh surprised everyone in the room.
Siobhan was the one who finally found the bug in the ingestion layer.
About twenty percent of the requests were failing silently before that fix landed.
Later we brought in Siobhan again to review the thirty five remaining edge cases.
It won't be easy to hit the deadline but the team is optimistic about it.
Honestly the whole thing was uh basically a lesson in patience for everyone involved.
We shipped the first version on a Friday afternoon, which in hindsight was risky.
The C I A style compartmentalization of the codebase actually helped a lot here.
Nobody expected the migration to go this smoothly given how old the system was.
It's still not perfect but the numbers keep improving every single week now.
Can't say we solved everything but the worst failure modes are gone for good.
""".split()  # noqa: SIM905 — a paragraph is far more readable to maintain than a 150-item list literal

FIXTURE_WORDS: list[STTWord] = [
    STTWord(text=t, start=float(i), end=float(i) + 0.4) for i, t in enumerate(_FIXTURE_TEXT)
]
N_GOLD = len(FIXTURE_WORDS)

_RATE_FIELDS = [f.name for f in fields(CorruptionConfig) if f.name.endswith("_rate")]


def zero_config(**overrides: float) -> CorruptionConfig:
    """A config with every rate at 0.0 except the ones named in `overrides`
    — used throughout to isolate a single transform's effect."""
    base = dict.fromkeys(_RATE_FIELDS, 0.0)
    base.update(overrides)
    return CorruptionConfig(**base)


def _binomial_ok(observed: int, n: int, p: float, z: float = 3.5) -> bool:
    """observed within z standard deviations of the binomial(n, p) mean.
    z=3.5 is deliberately generous — this is a sanity check on the sampling
    machinery, not a precise statistical claim."""
    mean = n * p
    sd = math.sqrt(n * p * (1 - p)) if 0 < p < 1 else 1.0
    return abs(observed - mean) <= max(z * sd, 1.0)


SEEDS = [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------
# level=0.0
# ---------------------------------------------------------------------


def test_level_zero_is_identity():
    out = corrupt(FIXTURE_WORDS, level=0.0, doc_id="fixture")
    assert out.tokens == tuple(w.text for w in FIXTURE_WORDS)
    assert all(not m.causes for m in out.mapping)
    assert out.deletions == ()


# ---------------------------------------------------------------------
# Determinism / seeding
# ---------------------------------------------------------------------


def test_same_seed_and_doc_id_is_byte_identical():
    a = corrupt(FIXTURE_WORDS, level=0.4, doc_id="doc-a", master_seed=7)
    b = corrupt(FIXTURE_WORDS, level=0.4, doc_id="doc-a", master_seed=7)
    assert a == b


def test_different_doc_id_diverges():
    a = corrupt(FIXTURE_WORDS, level=0.4, doc_id="doc-a", master_seed=7)
    b = corrupt(FIXTURE_WORDS, level=0.4, doc_id="doc-b", master_seed=7)
    assert a.tokens != b.tokens


def test_level_subset_property_in_isolation():
    """For a transform run in isolation (every other rate zeroed), the set
    of triggered opportunities at a low level must be a subset of those at
    a higher level, for the same seed/doc — the direct consequence of
    draw-then-threshold sampling with a level-independent seed."""
    low_cfg = zero_config(filler_removal_rate=CorruptionConfig().filler_removal_rate)
    for seed in SEEDS:
        low = corrupt(FIXTURE_WORDS, level=0.2, doc_id="subset", master_seed=seed, config=low_cfg)
        high = corrupt(FIXTURE_WORDS, level=0.8, doc_id="subset", master_seed=seed, config=low_cfg)
        low_deleted = {(d.gold_start, d.cause) for d in low.deletions}
        high_deleted = {(d.gold_start, d.cause) for d in high.deletions}
        assert low_deleted <= high_deleted


def test_transform_independence_through_real_pipeline():
    """Changing an unrelated, strictly-later transform's rate must not
    change what an earlier transform decided. casing_quote_normalization
    runs last, after filler_removal, so it cannot affect what filler_removal
    saw — tested by actually running the pipeline twice, not by inspecting
    the seed-derivation hash directly."""
    base = zero_config(filler_removal_rate=CorruptionConfig().filler_removal_rate)
    varied = zero_config(
        filler_removal_rate=CorruptionConfig().filler_removal_rate,
        casing_quote_normalization_rate=0.9,
    )
    a = corrupt(FIXTURE_WORDS, level=0.5, doc_id="indep", master_seed=3, config=base)
    b = corrupt(FIXTURE_WORDS, level=0.5, doc_id="indep", master_seed=3, config=varied)

    a_filler = [d for d in a.deletions if d.cause == "filler_removal"]
    b_filler = [d for d in b.deletions if d.cause == "filler_removal"]
    assert a_filler == b_filler


# ---------------------------------------------------------------------
# Manifest identity
# ---------------------------------------------------------------------


def test_config_hash_changes_with_config_and_is_stable_under_float_noise():
    a = corrupt(FIXTURE_WORDS, level=0.30000000000000004, doc_id="hash", master_seed=1)
    b = corrupt(FIXTURE_WORDS, level=0.3, doc_id="hash", master_seed=1)
    assert a.manifest.config_hash == b.manifest.config_hash

    c = corrupt(FIXTURE_WORDS, level=0.31, doc_id="hash", master_seed=1)
    assert a.manifest.config_hash != c.manifest.config_hash

    d = corrupt(
        FIXTURE_WORDS,
        level=0.3,
        doc_id="hash",
        master_seed=1,
        config=zero_config(filler_removal_rate=0.9),
    )
    assert a.manifest.config_hash != d.manifest.config_hash


def test_gold_hash_changes_with_text_and_with_timing():
    base = corrupt(FIXTURE_WORDS, level=0.3, doc_id="gh", master_seed=1)

    retimed = [STTWord(text=w.text, start=w.start + 10, end=w.end + 10) for w in FIXTURE_WORDS]
    retimed_out = corrupt(retimed, level=0.3, doc_id="gh", master_seed=1)
    assert base.manifest.gold_hash != retimed_out.manifest.gold_hash

    retexted = list(FIXTURE_WORDS)
    retexted[0] = STTWord(text="different", start=retexted[0].start, end=retexted[0].end)
    retexted_out = corrupt(retexted, level=0.3, doc_id="gh", master_seed=1)
    assert base.manifest.gold_hash != retexted_out.manifest.gold_hash


def test_resolved_config_names_match_transform_order():
    out = corrupt(FIXTURE_WORDS, level=0.5, doc_id="cfgnames", master_seed=1)
    names = {name for name, _ in out.manifest.resolved_config}
    assert names == set(TRANSFORM_ORDER)


# ---------------------------------------------------------------------
# Statistical: inverse coverage / reorder count, pooled across seeds
# ---------------------------------------------------------------------


def test_pooled_filler_removal_matches_target():
    n_opportunities = sum(
        1 for w in FIXTURE_WORDS if w.text.strip(",.!?").casefold() in FILLER_WORDS
    )
    rate = CorruptionConfig().filler_removal_rate * 0.6
    target_per_doc = min(round(rate * N_GOLD), n_opportunities)
    cfg = zero_config(filler_removal_rate=CorruptionConfig().filler_removal_rate)

    observed = 0
    for seed in SEEDS:
        out = corrupt(FIXTURE_WORDS, level=0.6, doc_id="pooled-filler", master_seed=seed, config=cfg)
        observed += sum(1 for d in out.deletions if d.cause == "filler_removal")

    p = target_per_doc / n_opportunities if n_opportunities else 0.0
    assert _binomial_ok(observed, n_opportunities * len(SEEDS), p)


def test_pooled_sentence_reorder_backward_pair_count_matches_swap_target():
    """non_monotonic_pair_fraction isn't proportional to swap count — a
    swap creates ~1 backward adjacent pair regardless of span length — so
    this asserts on the raw backward-pair count against the swap-count
    target directly, pooled across seeds as a binomial(n_gaps, p) count."""
    n_sentence_ends = sum(1 for t in _FIXTURE_TEXT if t.endswith((".", "!", "?")))
    n_sentences = n_sentence_ends if _FIXTURE_TEXT[-1].endswith((".", "!", "?")) else n_sentence_ends + 1
    n_gaps = max(1, n_sentences - 1)
    rate = CorruptionConfig().sentence_reorder_rate * 0.6
    target_swaps = min(round(rate / 100 * N_GOLD), n_gaps)
    p = target_swaps / n_gaps

    cfg = zero_config(sentence_reorder_rate=CorruptionConfig().sentence_reorder_rate)
    observed_pairs = 0
    for seed in SEEDS:
        out = corrupt(FIXTURE_WORDS, level=0.6, doc_id="pooled-reorder", master_seed=seed, config=cfg)
        flat = [gi for m in out.mapping for gi in m.gold_indices]
        observed_pairs += sum(1 for a, b in pairwise(flat) if b < a)

    # Each triggered swap contributes ~1 backward adjacent pair.
    assert _binomial_ok(observed_pairs, n_gaps * len(SEEDS), p)


# ---------------------------------------------------------------------
# Two naive baselines, scored against `mapping`.
#
# _greedy_monotonic_accuracy is a single forward pointer over gold text: it
# can desync and, unlike SequenceMatcher below, has no way back. An earlier
# version of this function `break`d the whole scoring loop the first time
# an edited token had no match anywhere in the remaining gold text (e.g. an
# editorial_insertion, which by construction never matches — it has no gold
# source at all) — that is "advance past a mismatch and never recover", the
# textbook greedy-monotonic failure mode, and it silently zeroed out
# scoring for the rest of the document from that point on. Fixed below to
# only skip the *search*, not the rest of the scan, when no match is found:
# `gi` no longer gets stranded at len(gold_texts).
#
# _sequence_matcher_accuracy (difflib.SequenceMatcher, matching S4's
# planned `align_baseline`) finds globally-good matching blocks instead of
# scanning once forward, so one bad token doesn't cascade. It exists
# specifically so there's a second number with a real gradient: the greedy
# baseline is dominated by *where* the first unmatchable token lands
# (seed-determined), the SequenceMatcher baseline is closer to *how much*
# corruption exists (level-determined).
# ---------------------------------------------------------------------


def _greedy_monotonic_accuracy(gold_words: list[STTWord], out) -> float:
    """Walk both streams in order, greedily matching equal (casefolded)
    text monotonically. On failure to find a match anywhere ahead, the
    current edited token scores 0 and `gi` is left where it was — the next
    edited token gets a fresh, unstranded search — rather than treating one
    unmatchable token as the end of scoring."""
    gold_texts = [w.text.casefold() for w in gold_words]
    correct = 0
    gi = 0
    for edited_index, token in enumerate(out.tokens):
        search = gi
        while search < len(gold_texts) and gold_texts[search] != token.casefold():
            search += 1
        if search >= len(gold_texts):
            continue  # no match anywhere ahead; this token is wrong, gi is untouched
        true_gold_indices = out.mapping[edited_index].gold_indices
        if search in true_gold_indices:
            correct += 1
        gi = search + 1
    return correct / len(out.tokens) if out.tokens else 1.0


def _sequence_matcher_accuracy(gold_words: list[STTWord], out) -> float:
    """difflib.SequenceMatcher over casefolded text finds globally-good
    matching blocks rather than one forward scan, so it can't get
    permanently stranded by a single unmatchable token the way the greedy
    baseline can."""
    import difflib

    gold_texts = [w.text.casefold() for w in gold_words]
    edited_texts = [t.casefold() for t in out.tokens]
    matcher = difflib.SequenceMatcher(None, gold_texts, edited_texts, autojunk=False)

    correct = 0
    for gold_start, edited_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            true_gold_indices = out.mapping[edited_start + offset].gold_indices
            if (gold_start + offset) in true_gold_indices:
                correct += 1
    return correct / len(out.tokens) if out.tokens else 1.0


def test_baseline_scores_perfectly_at_level_zero():
    """Decisive one-line check, run before trusting any other baseline
    number: level=0.0 is byte-identical to gold, so both baselines must
    score exactly 1.0. If this fails, a baseline is bugged and every other
    number computed with it is meaningless — this caught exactly that bug
    once (see module docstring above _greedy_monotonic_accuracy)."""
    out = corrupt(FIXTURE_WORDS, level=0.0, doc_id="baseline-zero", master_seed=1)
    assert _greedy_monotonic_accuracy(FIXTURE_WORDS, out) == 1.0
    assert _sequence_matcher_accuracy(FIXTURE_WORDS, out) == 1.0


def test_naive_baseline_is_not_saturated_and_degrades_with_level():
    low = corrupt(FIXTURE_WORDS, level=0.15, doc_id="baseline", master_seed=1)
    high = corrupt(FIXTURE_WORDS, level=0.8, doc_id="baseline", master_seed=1)

    low_acc = _sequence_matcher_accuracy(FIXTURE_WORDS, low)
    high_acc = _sequence_matcher_accuracy(FIXTURE_WORDS, high)

    assert low_acc < 0.98, "benchmark is saturated at a low level — no headroom to measure improvement"
    assert high_acc < low_acc


# ---------------------------------------------------------------------
# Property test: universal invariants over a seed x level grid
# ---------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("level", [0.0, 0.2, 0.4, 0.6, 1.0])
def test_invariants_hold_over_seed_and_level_grid(seed, level):
    out = corrupt(FIXTURE_WORDS, level=level, doc_id="grid", master_seed=seed)

    assert len(out.mapping) == len(out.tokens)
    for i, m in enumerate(out.mapping):
        assert m.edited_index == i
        for gi in m.gold_indices:
            assert 0 <= gi < N_GOLD

    relations = classify_all(out.mapping)
    for m, rel in zip(out.mapping, relations):
        assert (rel == EditRelation.INSERTED) == (m.gold_indices == ())

    # deletions non-overlapping and sorted by gold_start
    prev_end = -1
    for d in out.deletions:
        assert d.gold_start < d.gold_end
        assert d.gold_start >= prev_end
        prev_end = d.gold_end


# ---------------------------------------------------------------------
# Per-transform focused checks
# ---------------------------------------------------------------------


def _isolated(config_field: str, rate: float = 1.0, level: float = 1.0, doc_id: str = "iso"):
    cfg = zero_config(**{config_field: rate})
    return corrupt(FIXTURE_WORDS, level=level, doc_id=doc_id, config=cfg)


def test_contraction_expansion_produces_split():
    out = _isolated("contraction_expansion_rate")
    relations = classify_all(out.mapping)
    assert EditRelation.SPLIT in relations
    split_entries = [m for m, r in zip(out.mapping, relations) if r == EditRelation.SPLIT]
    assert all("contraction_expansion" in m.causes for m in split_entries)


def test_acronym_collapse_produces_merge():
    out = _isolated("acronym_collapse_rate")
    relations = classify_all(out.mapping)
    merges = [m for m, r in zip(out.mapping, relations) if r == EditRelation.MERGE]
    assert any("acronym_collapse" in m.causes for m in merges)


def test_numeral_conversion_produces_merge():
    out = _isolated("numeral_conversion_rate")
    relations = classify_all(out.mapping)
    merges = [m for m, r in zip(out.mapping, relations) if r == EditRelation.MERGE]
    assert any("numeral_conversion" in m.causes for m in merges)


def test_repetition_collapse_produces_merge_not_deletion():
    out = _isolated("repetition_collapse_rate")
    relations = classify_all(out.mapping)
    merges = [m for m, r in zip(out.mapping, relations) if r == EditRelation.MERGE]
    assert any("repetition_collapse" in m.causes for m in merges)


def test_repetition_collapse_skips_units_already_touched_by_an_earlier_transform():
    """repetition_collapse's opportunity filter requires BOTH repeated units
    to have empty `causes`. At the pinned TRANSFORM_ORDER this guard is
    currently unreachable in the real pipeline — everything ahead of it
    (whole_span_deletion, false_start_deletion, filler_removal) only
    deletes, so no surviving unit ever carries a non-empty `causes` by the
    time repetition_collapse runs (confirmed by mutation: dropping the
    `causes` union there produced byte-identical output). That does NOT
    make it dead code in general: move a substituting transform like
    contraction_expansion ahead of repetition_collapse in TRANSFORM_ORDER,
    and a "we we" -> "we" collapse where one "we" came from an expanded
    contraction would silently stop collapsing. Pinned directly here,
    independent of pipeline order, so this guard's semantics don't rot into
    another incidentally-unreachable branch the next time someone touches
    TRANSFORM_ORDER."""
    units = [
        _Unit(text="we", gold_indices=(0,), causes=frozenset({"contraction_expansion"})),
        _Unit(text="we", gold_indices=(1,)),
    ]
    cfg = CorruptionConfig(repetition_collapse_rate=1.0)
    out, _deletions = repetition_collapse(units, [], random.Random(0), 2, cfg, {})
    assert out == units, "a repeated unit with non-empty causes must not be collapsed"


def test_editorial_insertion_has_no_gold_source():
    out = _isolated("editorial_insertion_rate")
    relations = classify_all(out.mapping)
    inserted = [m for m, r in zip(out.mapping, relations) if r == EditRelation.INSERTED]
    assert inserted
    assert all(m.gold_indices == () for m in inserted)
    assert all("editorial_insertion" in m.causes for m in inserted)


@pytest.mark.parametrize(
    "config_field,cause",
    [
        ("whole_span_deletion_rate", "whole_span_deletion"),
        ("false_start_rate", "false_start_deletion"),
        ("filler_removal_rate", "filler_removal"),
    ],
)
def test_deletion_transforms_record_cause(config_field, cause):
    out = _isolated(config_field)
    assert any(d.cause == cause for d in out.deletions)


def test_asr_name_correction_is_substitute():
    out = _isolated("asr_name_correction_rate")
    relations = classify_all(out.mapping)
    substituted = [m for m, r in zip(out.mapping, relations) if r == EditRelation.SUBSTITUTE]
    assert any("asr_name_correction" in m.causes for m in substituted)


def test_sentence_reorder_tags_causes_on_moved_tokens():
    out = _isolated("sentence_reorder_rate", rate=CorruptionConfig().sentence_reorder_rate)
    assert any("sentence_reorder" in m.causes for m in out.mapping)


# ---------------------------------------------------------------------
# Mutation-resistance: properties that were design decisions, not just
# outputs, plus a pinned golden output. A mutation pass (halve a rate,
# drop a transform from TRANSFORM_ORDER, swap two entries in it, drop a
# `causes` union so it overwrites, change a seed-derivation input) showed
# the tests above stay green under a halved rate or a swapped transform
# order — both change actual output but not anything those tests pin to
# an absolute value. The golden test below closes exactly that gap.
# ---------------------------------------------------------------------


def test_causes_accumulate_across_transforms_not_overwritten():
    """Two transforms touching the same unit must UNION their names into
    `causes`, never overwrite. asr_name_correction substitutes a name early
    in the pipeline; sentence_reorder can later move the sentence containing
    that substituted token. If sentence_reorder's union were replaced with
    an overwrite, the asr_name_correction tag would be lost — this is
    exactly the class of bug a diff-at-the-end reimplementation would also
    silently produce."""
    cfg = zero_config(
        asr_name_correction_rate=CorruptionConfig().asr_name_correction_rate,
        sentence_reorder_rate=CorruptionConfig().sentence_reorder_rate,
    )
    out = corrupt(FIXTURE_WORDS, level=1.0, doc_id="union-check", master_seed=1, config=cfg)
    multi_cause = [
        m for m in out.mapping if "asr_name_correction" in m.causes and "sentence_reorder" in m.causes
    ]
    assert multi_cause, "expected at least one token touched by both transforms with both causes retained"


def test_transform_rate_denominator_is_original_gold_count():
    """Every transform's target is round(rate * n_gold) using the ORIGINAL
    gold count fixed for the whole pipeline, never len(units) at that
    transform's position — which shrinks as earlier transforms delete
    tokens. If it used the surviving count, rates would stop composing
    linearly with `level` and expectations would become order-dependent,
    exactly what CorruptionConfig's docstring rules out.

    Verified directly against filler_removal (bypassing the full pipeline,
    so this is deterministic rather than needing a fixture shaped just
    right): n_gold is set far larger than len(units), so a correct
    (n_gold-denominated) target saturates past the opportunity count and
    every filler word is removed regardless of rng seed. A len(units)-
    denominated target would stay below the opportunity count instead, and
    selection would vary by seed — this loop would then fail on at least
    one of the ten seeds below.
    """
    units = [_Unit(text="um", gold_indices=(i,)) for i in range(5)]
    cfg = CorruptionConfig(filler_removal_rate=0.5)
    huge_n_gold = 1000  # >> len(units) == 5

    for seed in range(10):
        rng = random.Random(seed)
        kept, deletions = filler_removal(units, [], rng, huge_n_gold, cfg, {})
        assert kept == []
        assert len(deletions) == 5


_GOLDEN_LEVEL = 0.4
_GOLDEN_SEED = 123
_GOLDEN_DOC_ID = "golden-fixture"
_GOLDEN_CONFIG_HASH = "ba486ff0f56952bbf2beadf56b3e1c56369dd87f199c411d2ea454ee8674fea9"
_GOLDEN_GOLD_HASH = "06892cf916e9b4906ded09fd6c82897cb9f6d2bdd8cb3b24d4169f30c2fa81ba"
_GOLDEN_OUTPUT_HASH = "5e5d523d2282e1c5c55b40ebb923e6e2e687c841b595720db964994dcc84302f"


def _canonical_output_repr(out) -> str:
    return "\n".join(
        [
            "TOKENS:" + "|".join(out.tokens),
            "MAPPING:"
            + ";".join(
                f"{m.edited_index}:{','.join(map(str, m.gold_indices))}:{','.join(sorted(m.causes))}"
                for m in out.mapping
            ),
            "DELETIONS:" + ";".join(f"{d.gold_start}-{d.gold_end}:{d.cause}" for d in out.deletions),
        ]
    )


def test_golden_output_pinned_at_fixed_seed_doc_level():
    """Pins the exact output (tokens, mapping, deletions, config/gold hash)
    of one fixed (master_seed, doc_id, level) run against the default
    CorruptionConfig and TRANSFORM_ORDER.

    This is the only check in the suite that actually enforces
    GENERATOR_VERSION discipline. A mutation pass confirmed every other
    test here stays green under a halved transform rate or two swapped
    entries in TRANSFORM_ORDER — both change real output, just not
    anything pinned to an absolute value. This test is that absolute
    value.

    If this test needs to change: that means transform logic, a rate, or
    the pipeline order changed on purpose. Bump GENERATOR_VERSION by hand
    in corruptor.py, regenerate these constants deliberately (don't
    copy-paste a failing run's actual output without reading the diff
    first), and say in the commit message why the golden output moved.
    """
    out = corrupt(FIXTURE_WORDS, level=_GOLDEN_LEVEL, doc_id=_GOLDEN_DOC_ID, master_seed=_GOLDEN_SEED)

    # Assert manifest fields individually, not just the content hash below,
    # so a failure names *what* moved (order vs. a rate vs. real logic)
    # instead of every cause reporting the same "hash mismatch".
    assert out.manifest.transform_order == TRANSFORM_ORDER, "TRANSFORM_ORDER changed"
    assert dict(out.manifest.resolved_config) == CorruptionConfig().resolved(_GOLDEN_LEVEL), (
        "a base rate in CorruptionConfig changed"
    )
    assert out.manifest.gold_hash == _GOLDEN_GOLD_HASH, "gold fixture (FIXTURE_WORDS) changed"
    assert out.manifest.config_hash == _GOLDEN_CONFIG_HASH, (
        "config_hash changed despite transform_order and resolved_config matching above — "
        "check _config_hash's own logic"
    )

    digest = hashlib.sha256(_canonical_output_repr(out).encode()).hexdigest()
    assert digest == _GOLDEN_OUTPUT_HASH, (
        "transform_order, resolved_config, and both hashes above all matched, but the actual "
        "tokens/mapping/deletions changed — a transform's internal logic regressed. If "
        "intentional, bump GENERATOR_VERSION and update the pinned constants deliberately"
    )


def test_effective_config_reveals_saturation_at_benchmarked_levels():
    """`level` is a lie for a saturated transform: its target already
    exceeds its opportunity count, `_select` silently clamps to that
    ceiling, and increasing `level` further changes nothing. This asserts
    the clamp is a manifest fact (`effective_config`) rather than only
    documented in a README table that goes stale the moment the fixture or
    rates change.

    A transform is saturated at a level iff its achieved rate is identical
    across every independently-seeded run: saturation means `_select`'s
    inclusion probability p == 1.0, which makes selection deterministic
    (no draw can fail); an unsaturated transform has p < 1.0, so its
    achieved rate varies by seed almost certainly. This is a cleaner
    signal than comparing achieved to resolved directly, since a low-
    probability *unsaturated* transform can also land on the same value
    by chance for one seed (e.g. "0 events fired" at both a low and a
    high level does not by itself mean saturation).

    On this fixture, at level=0.1, only sentence_reorder and
    editorial_insertion carry any real dynamic range — the other 9 of 11
    transforms are already fully saturated. That's the root cause behind
    the README's flat baseline numbers, and it's the reason a single small
    fixture cannot support this benchmark: this assertion is deliberately
    weak (>= 2, the current true count) so it fails loudly, naming the
    saturated set, the moment someone tries to lean on more transforms
    than the fixture can actually support.

    Identical achieved *rate* across seeds proves saturation only if the
    achieved *set* is also identical for a reason other than "there was
    only one possible set" — a transform whose sampling is accidentally
    seed-independent (a real bug: e.g. a stray module-level `random` call,
    or an RNG seeded without `doc_id`/`name`) would show the exact same
    symptom. For every transform this test calls unsaturated, it also
    asserts the *specific gold indices touched* differ across at least two
    seeds — not just the count — which a seed-independence bug could not
    fake. (This does not fully close the gap for a transform whose target
    happens to exactly equal its opportunity count: that case is
    legitimately saturated and legitimately produces an identical set every
    time, indistinguishable from a bug by this test alone. None of the
    current 11 transforms are known to sit at that exact boundary on this
    fixture, so it's a documented residual gap, not a silent one.)
    """
    for level in (0.1, 0.3, 0.5):
        achieved_by_seed: dict[str, set[float]] = {name: set() for name in TRANSFORM_ORDER}
        touched_by_seed: dict[str, list[frozenset[int]]] = {name: [] for name in TRANSFORM_ORDER}
        for seed in SEEDS:
            out = corrupt(FIXTURE_WORDS, level=level, doc_id="saturation-check", master_seed=seed)
            for name, value in out.manifest.effective_config:
                achieved_by_seed[name].add(round(value, 9))
            for name in TRANSFORM_ORDER:
                touched_by_seed[name].append(_touched_gold_indices(out, name))

        unsaturated = [name for name, vals in achieved_by_seed.items() if len(vals) > 1]
        saturated = [name for name, vals in achieved_by_seed.items() if len(vals) <= 1]
        assert len(unsaturated) >= 2, (
            f"level={level}: only {unsaturated} show any seed-to-seed variation; "
            f"{saturated} are fully saturated (deterministic across all seeds) — "
            "level has no effect on the saturated set at this level"
        )

        for name in unsaturated:
            distinct_sets = {frozenset(s) for s in touched_by_seed[name]}
            assert len(distinct_sets) > 1, (
                f"level={level}: {name}'s achieved rate varies by seed, but the exact same "
                f"gold indices {touched_by_seed[name][0]} were touched every time — that's "
                "consistent with a seed-independence bug (RNG not actually varying by seed), "
                "not with genuine probabilistic selection"
            )


def _touched_gold_indices(out, cause: str) -> frozenset[int]:
    """Gold indices a given transform actually touched in one corrupt() run
    — from `deletions` (deletion-type transforms) and from `mapping` entries
    carrying `cause` (substitution/merge/reorder-type transforms). Used to
    verify seed-to-seed variation is real (different indices selected), not
    just a different-looking aggregate rate.

    editorial_insertion is a special case: an INSERTED unit has no gold
    source at all (`gold_indices == ()`), so it contributes nothing to
    either set above even when it fires. Anchored instead to the gold index
    of the nearest preceding unit that does have one — "touched" means
    "inserted right after this gold token" — so insertion position is still
    comparable across seeds."""
    from_deletions = {gi for d in out.deletions if d.cause == cause for gi in range(d.gold_start, d.gold_end)}
    from_mapping = {gi for m in out.mapping if cause in m.causes for gi in m.gold_indices}
    if from_deletions or from_mapping:
        return frozenset(from_deletions | from_mapping)

    anchors: set[int] = set()
    prev_gold = -1
    for m in out.mapping:
        if cause in m.causes and not m.gold_indices:
            anchors.add(prev_gold)
        if m.gold_indices:
            prev_gold = m.gold_indices[-1]
    return frozenset(anchors)


# ---------------------------------------------------------------------
# Cross-process determinism: str.__hash__ is randomized per process
# (PYTHONHASHSEED), so any accidental hash()/set-iteration-order
# dependence gives in-run determinism but cross-run drift — invisible to
# every test above, which only ever compares runs within one process.
# ---------------------------------------------------------------------


def test_deterministic_across_processes_with_different_hash_seeds():
    script = (
        "import sys; sys.path.insert(0, 'src'); "
        "from anchor_align.corrupt.corruptor import corrupt; "
        "from anchor_align.models import STTWord; "
        "words = [STTWord(text=t, start=float(i), end=float(i) + 0.4) "
        f"for i, t in enumerate({_FIXTURE_TEXT!r})]; "
        "out = corrupt(words, level=0.4, doc_id='hashseed-check', master_seed=99); "
        "print(out.manifest.config_hash); print(out.manifest.gold_hash); "
        "print('|'.join(out.tokens))"
    )

    def run_with_hash_seed(seed: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": os.environ.get("PATH", "")},
            cwd=Path(__file__).resolve().parents[2],
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    out_a = run_with_hash_seed("0")
    out_b = run_with_hash_seed("1")
    assert out_a == out_b, "output diverged across PYTHONHASHSEED values — a hash()/set-order dependency leaked in"
