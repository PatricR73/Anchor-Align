"""S1 — corruption generator.

Takes ground-truth (word, timing) pairs and produces an artificially
"human-edited" version, plus the mapping back to ground truth. This is the
measurement harness for every alignment improvement, so two rules are
load-bearing everywhere below:

1. Never diff at the end. Each transform threads the same `_Unit` records
   through the pipeline, unioning provenance into `causes` as it goes,
   instead of running every transform and reconstructing alignment
   afterwards — that would silently reintroduce the exact problem this
   module exists to benchmark.
2. Never touch the global `random` module. Every transform draws from its
   own `random.Random` seeded from `(master_seed, transform_name, doc_id)`
   — independent of `level` and of every other transform — so adding a
   transform, or changing one transform's rate, cannot perturb any other
   transform's draws or any other document's corpus.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
from dataclasses import dataclass, replace

from anchor_align.contractions import CONTRACTIONS
from anchor_align.models import (
    CorruptedTranscript,
    CorruptionManifest,
    DeletionRecord,
    STTWord,
    TokenMapping,
)

logger = logging.getLogger(__name__)

# Bumped by hand whenever transform *logic* changes (not config). Folded
# into `config_hash` so a logic change with identical resolved config still
# changes dataset identity — the silent-drift case this scheme exists to
# prevent.
GENERATOR_VERSION = "0.1.0"


# --------------------------------------------------------------------------
# Working representation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Unit:
    """Internal pipeline record. `gold_indices` is empty iff this unit has
    no spoken source (an editorial insertion). `causes` is purely
    additive: a transform unions its own name in, never overwriting what
    an earlier transform recorded."""

    text: str
    gold_indices: tuple[int, ...]
    causes: frozenset[str] = frozenset()


def _rng_for(master_seed: int, name: str, doc_id: str) -> random.Random:
    digest = hashlib.sha256(f"{master_seed}:{name}:{doc_id}".encode()).digest()
    # Full digest, not truncated: random.Random accepts arbitrary-width
    # ints and truncating would just discard entropy.
    return random.Random(int.from_bytes(digest, "big"))


def _select(rng: random.Random, n_opportunities: int, target: int) -> list[bool]:
    """Draw-then-threshold: one draw per opportunity, unconditionally, in a
    fixed stable order. Never draw only when already planning to act —
    that is what makes level=0.1 output a strict subset of level=0.3
    output for a transform run in isolation (same seed => same draw
    sequence; a higher level only raises the inclusion probability)."""
    if n_opportunities == 0:
        return []
    target = min(target, n_opportunities)
    p = target / n_opportunities
    return [rng.random() < p for _ in range(n_opportunities)]


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CorruptionConfig:
    """Per-transform base rates at level=1.0; actual rate = base_rate * level.

    Every rate is the **expected fraction of the *original* gold token
    count** (`n_gold`, fixed for the whole pipeline — never the surviving
    count at a given transform's position, or rates would stop composing
    linearly with `level`). A transform's target count is
    `round(resolved_rate * n_gold)`, clamped to its actual opportunity
    count when it runs — asking for more than is available saturates
    rather than erroring. Rates are independent per-transform targets, not
    a shared budget.

    `sentence_reorder_rate` is the one exception: it's **swaps per hundred
    original gold tokens**, not a token fraction — swapping two adjacent
    spans produces roughly one backward adjacent pair regardless of span
    length.
    """

    whole_span_deletion_rate: float = 0.06
    whole_span_chunk_len: int = 20

    false_start_rate: float = 0.06
    false_start_chunk_len: int = 3

    filler_removal_rate: float = 0.5
    repetition_collapse_rate: float = 0.7
    asr_name_correction_rate: float = 0.7
    contraction_expansion_rate: float = 0.7
    numeral_conversion_rate: float = 0.7
    acronym_collapse_rate: float = 0.7

    sentence_reorder_rate: float = 3.0  # swaps per 100 original gold tokens

    editorial_insertion_rate: float = 0.03
    casing_quote_normalization_rate: float = 0.5

    def resolved(self, level: float) -> dict[str, float]:
        return {name: rate * level for name, rate in self.base_rates().items()}

    def base_rates(self) -> dict[str, float]:
        return {
            "whole_span_deletion": self.whole_span_deletion_rate,
            "false_start_deletion": self.false_start_rate,
            "filler_removal": self.filler_removal_rate,
            "repetition_collapse": self.repetition_collapse_rate,
            "asr_name_correction": self.asr_name_correction_rate,
            "contraction_expansion": self.contraction_expansion_rate,
            "numeral_conversion": self.numeral_conversion_rate,
            "acronym_collapse": self.acronym_collapse_rate,
            "sentence_reorder": self.sentence_reorder_rate,
            "editorial_insertion": self.editorial_insertion_rate,
            "casing_quote_normalization": self.casing_quote_normalization_rate,
        }


# Pinned transform order — real editing is cut-then-polish, not
# polish-then-cut: whole-span and false-start cuts happen first so nothing
# downstream edits tokens about to disappear; casing/quote normalization
# runs last so it also normalizes text every earlier transform introduced.
TRANSFORM_ORDER: tuple[str, ...] = (
    "whole_span_deletion",
    "false_start_deletion",
    "filler_removal",
    "repetition_collapse",
    "asr_name_correction",
    "contraction_expansion",
    "numeral_conversion",
    "acronym_collapse",
    "sentence_reorder",
    "editorial_insertion",
    "casing_quote_normalization",
)


# --------------------------------------------------------------------------
# Transforms
# --------------------------------------------------------------------------


def _record(achieved: dict[str, float] | None, cause: str, value: float) -> None:
    """Every transform's `achieved` param is optional: `corrupt()` passes a
    real dict to accumulate achieved-vs-resolved rates into the manifest,
    but transforms are also public functions some tests call directly."""
    if achieved is not None:
        achieved[cause] = value


def _chunked_deletion(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    *,
    rate: float,
    chunk_len: int,
    cause: str,
    achieved: dict[str, float] | None = None,
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Shared engine for whole_span_deletion and false_start_deletion: the
    gold token stream is divided into fixed, non-overlapping chunks
    (stable regardless of level, since both transforms run before anything
    upstream could change unit identity), and each chunk is an opportunity
    to cut. Distinct chunk lengths give the two transforms their distinct
    character — a handful of long cuts for tangents, many short cuts for
    false starts."""
    n_chunks = max(1, len(units) // chunk_len) if units else 0
    target = round(rate * n_gold / chunk_len) if chunk_len else 0
    selected = _select(rng, n_chunks, target)
    # Token-equivalent, not chunk count: resolved_config is a token
    # fraction of n_gold, so achieved must be denominated the same way.
    _record(achieved, cause, (sum(selected) * chunk_len / n_gold) if n_gold else 0.0)

    kept: list[_Unit] = []
    new_deletions: list[DeletionRecord] = []
    for chunk_index in range(n_chunks):
        start = chunk_index * chunk_len
        end = start + chunk_len if chunk_index < n_chunks - 1 else len(units)
        chunk = units[start:end]
        if selected[chunk_index] and chunk:
            gold_ids = [gi for u in chunk for gi in u.gold_indices]
            if gold_ids:
                new_deletions.append(
                    DeletionRecord(gold_start=min(gold_ids), gold_end=max(gold_ids) + 1, cause=cause)
                )
        else:
            kept.extend(chunk)
    return kept, deletions + new_deletions


def whole_span_deletion(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Editor cuts a large tangent — structurally different from word-level
    deletion: one big timing gap rather than many small ones."""
    return _chunked_deletion(
        units,
        deletions,
        rng,
        n_gold,
        rate=cfg.whole_span_deletion_rate,
        chunk_len=cfg.whole_span_chunk_len,
        cause="whole_span_deletion",
        achieved=achieved,
    )


def false_start_deletion(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Editor cuts an abandoned clause the speaker restarted."""
    return _chunked_deletion(
        units,
        deletions,
        rng,
        n_gold,
        rate=cfg.false_start_rate,
        chunk_len=cfg.false_start_chunk_len,
        cause="false_start_deletion",
        achieved=achieved,
    )


FILLER_WORDS = frozenset({"um", "uh", "er", "like", "actually", "basically"})


def filler_removal(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Editor drops filler words the speaker used but didn't mean."""
    opportunities = [i for i, u in enumerate(units) if u.text.strip(",.!?").casefold() in FILLER_WORDS]
    target = round(cfg.filler_removal_rate * n_gold)
    selected = _select(rng, len(opportunities), target)
    achieved["filler_removal"] = (sum(selected) / n_gold) if n_gold else 0.0

    to_delete = {opportunities[i] for i, hit in enumerate(selected) if hit}
    kept = [u for i, u in enumerate(units) if i not in to_delete]
    new_deletions = [
        DeletionRecord(gold_start=u.gold_indices[0], gold_end=u.gold_indices[0] + 1, cause="filler_removal")
        for i, u in enumerate(units)
        if i in to_delete
        for u in [units[i]]
    ]
    return kept, deletions + new_deletions


def repetition_collapse(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Editor collapses a stutter/repeated word ("we we went" -> "we went").
    Pinned as MERGE, not deletion: the surviving token's gold_indices
    spans both repeated positions, more truthful for timing than recording
    the dropped repeat as a deletion with no surviving referent."""
    opportunities = [
        i
        for i in range(len(units) - 1)
        if units[i].text.casefold() == units[i + 1].text.casefold() and not units[i].causes and not units[i + 1].causes
    ]
    target = round(cfg.repetition_collapse_rate * n_gold)
    selected = _select(rng, len(opportunities), target)
    achieved["repetition_collapse"] = (sum(selected) / n_gold) if n_gold else 0.0
    merge_at = {opportunities[i] for i, hit in enumerate(selected) if hit}

    out: list[_Unit] = []
    skip_next = False
    for i, u in enumerate(units):
        if skip_next:
            skip_next = False
            continue
        if i in merge_at:
            nxt = units[i + 1]
            out.append(
                _Unit(
                    text=u.text,
                    gold_indices=u.gold_indices + nxt.gold_indices,
                    causes=u.causes | nxt.causes | {"repetition_collapse"},
                )
            )
            skip_next = True
        else:
            out.append(u)
    return out, deletions


ASR_NAME_CORRECTIONS = {"siobhan": "Shivon", "yosemite": "Yosemiti"}


def asr_name_correction(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Substitute a plausible ASR mishearing for a name/term. Same single
    gold source, real timing — the "opposite case" from an editorial
    insertion that the mapping design exists to keep distinct."""
    opportunities = [i for i, u in enumerate(units) if u.text.casefold() in ASR_NAME_CORRECTIONS]
    target = round(cfg.asr_name_correction_rate * n_gold)
    selected = _select(rng, len(opportunities), target)
    achieved["asr_name_correction"] = (sum(selected) / n_gold) if n_gold else 0.0
    hit_at = {opportunities[i] for i, hit in enumerate(selected) if hit}

    out = []
    for i, u in enumerate(units):
        if i in hit_at:
            replacement = ASR_NAME_CORRECTIONS[u.text.casefold()]
            out.append(_Unit(text=replacement, gold_indices=u.gold_indices, causes=u.causes | {"asr_name_correction"}))
        else:
            out.append(u)
    return out, deletions


def contraction_expansion(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """"don't" -> "do" + "not": one gold source, two edited tokens (SPLIT)."""
    opportunities = [i for i, u in enumerate(units) if u.text.casefold() in CONTRACTIONS]
    target = round(cfg.contraction_expansion_rate * n_gold)
    selected = _select(rng, len(opportunities), target)
    achieved["contraction_expansion"] = (sum(selected) / n_gold) if n_gold else 0.0
    hit_at = {opportunities[i] for i, hit in enumerate(selected) if hit}

    out: list[_Unit] = []
    for i, u in enumerate(units):
        if i in hit_at:
            a, b = CONTRACTIONS[u.text.casefold()]
            causes = u.causes | {"contraction_expansion"}
            out.append(_Unit(text=a, gold_indices=u.gold_indices, causes=causes))
            out.append(_Unit(text=b, gold_indices=u.gold_indices, causes=causes))
        else:
            out.append(u)
    return out, deletions


ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
NUM_WORDS = {**ONES, **TEENS, **TENS}


def numeral_conversion(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """"twenty percent" -> "20%": two gold sources, one edited token (MERGE).
    This is words->digits, the opposite direction from num2words — hence
    the small hand-rolled parser here. Intentionally narrow: this is a
    corruption generator, not a general text-to-number library."""
    opportunities = []
    for i in range(len(units) - 1):
        a, b = units[i].text.casefold(), units[i + 1].text.casefold()
        # (numeral + "percent") or (tens + ones) merge into one token
        if (a in NUM_WORDS and b == "percent") or (a in TENS and b in ONES):
            opportunities.append(i)

    target = round(cfg.numeral_conversion_rate * n_gold)
    selected = _select(rng, len(opportunities), target)
    achieved["numeral_conversion"] = (sum(selected) / n_gold) if n_gold else 0.0
    merge_at = {opportunities[i] for i, hit in enumerate(selected) if hit}

    out: list[_Unit] = []
    skip_next = False
    for i, u in enumerate(units):
        if skip_next:
            skip_next = False
            continue
        if i in merge_at:
            nxt = units[i + 1]
            a, b = u.text.casefold(), nxt.text.casefold()
            merged = f"{NUM_WORDS[a]}%" if b == "percent" else str(TENS[a] + ONES[b])
            out.append(
                _Unit(
                    text=merged,
                    gold_indices=u.gold_indices + nxt.gold_indices,
                    causes=u.causes | nxt.causes | {"numeral_conversion"},
                )
            )
            skip_next = True
        else:
            out.append(u)
    return out, deletions


_SINGLE_LETTER = re.compile(r"^[A-Za-z]$")


def acronym_collapse(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """"F B I" -> "FBI": a run of spelled-out letters merges into one token."""
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(units):
        if _SINGLE_LETTER.match(units[i].text):
            j = i
            while j < len(units) and _SINGLE_LETTER.match(units[j].text):
                j += 1
            if j - i >= 2:
                runs.append((i, j))
            i = j
        else:
            i += 1

    target = round(cfg.acronym_collapse_rate * n_gold)
    selected = _select(rng, len(runs), target)
    achieved["acronym_collapse"] = (sum(selected) / n_gold) if n_gold else 0.0
    chosen = {runs[i] for i, hit in enumerate(selected) if hit}

    out: list[_Unit] = []
    i = 0
    while i < len(units):
        run = next((r for r in chosen if r[0] == i), None)
        if run:
            start, end = run
            chunk = units[start:end]
            merged_text = "".join(u.text.upper() for u in chunk)
            gold_ids = tuple(gi for u in chunk for gi in u.gold_indices)
            causes = frozenset().union(*(u.causes for u in chunk)) | {"acronym_collapse"}
            out.append(_Unit(text=merged_text, gold_indices=gold_ids, causes=causes))
            i = end
        else:
            out.append(units[i])
            i += 1
    return out, deletions


_SENTENCE_END = re.compile(r"[.!?]$")


def _sentence_spans(units: list[_Unit]) -> list[tuple[int, int]]:
    spans = []
    start = 0
    for i, u in enumerate(units):
        if _SENTENCE_END.search(u.text):
            spans.append((start, i + 1))
            start = i + 1
    if start < len(units):
        spans.append((start, len(units)))
    return spans


def sentence_reorder(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Swap two adjacent sentence-level spans — the source of non-monotonic
    gold-index order. `sentence_reorder` still unions its name into every
    moved token's `causes` even though the relation itself is derived from
    the final mapping: *which transform is responsible* for a token's
    position is not derivable from the mapping alone."""
    spans = _sentence_spans(units)
    n_gaps = max(0, len(spans) - 1)
    target = round(cfg.sentence_reorder_rate / 100 * n_gold)
    selected = _select(rng, n_gaps, target)
    # Same unit as sentence_reorder_rate itself: swaps per 100 original
    # gold tokens, not a token fraction — see CorruptionConfig's docstring.
    achieved["sentence_reorder"] = (sum(selected) / n_gold * 100) if n_gold else 0.0

    reordered_spans = list(spans)
    for gap in range(n_gaps):
        if selected[gap]:
            reordered_spans[gap], reordered_spans[gap + 1] = reordered_spans[gap + 1], reordered_spans[gap]

    placed: list[tuple[tuple[int, int], list[_Unit]]] = []
    for idx, (start, end) in enumerate(spans):
        span_units = units[start:end]
        moved = reordered_spans[idx] != (start, end)
        if moved:
            span_units = [
                replace(u, causes=u.causes | {"sentence_reorder"}) for u in span_units
            ]
        placed.append((reordered_spans[idx], span_units))
    placed.sort(key=lambda pair: pair[0][0])
    flat = [u for _, span_units in placed for u in span_units]
    return flat, deletions


TRANSITIONS = ("So,", "Now,", "Look,", "Anyway,")


def editorial_insertion(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Editor adds a transition word with no spoken source at all —
    INSERTED (empty gold_indices), the opposite case from a SUBSTITUTE."""
    n_gaps = max(0, len(units) - 1)
    target = round(cfg.editorial_insertion_rate * n_gold)
    selected = _select(rng, n_gaps, target)
    achieved["editorial_insertion"] = (sum(selected) / n_gold) if n_gold else 0.0

    out: list[_Unit] = []
    for i, u in enumerate(units):
        out.append(u)
        if i < n_gaps and selected[i]:
            word = TRANSITIONS[rng.randrange(len(TRANSITIONS))]
            out.append(_Unit(text=word, gold_indices=(), causes=frozenset({"editorial_insertion"})))
    return out, deletions


_CURLY_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def casing_quote_normalization(
    units: list[_Unit],
    deletions: list[DeletionRecord],
    rng: random.Random,
    n_gold: int,
    cfg: CorruptionConfig,
    achieved: dict[str, float],
) -> tuple[list[_Unit], list[DeletionRecord]]:
    """Normalize curly quotes to straight quotes. Deliberately trivial —
    its purpose is to keep exact-match baselines from looking artificially
    bad."""
    opportunities = [i for i, u in enumerate(units) if u.text != u.text.translate(_CURLY_QUOTES)]
    target = round(cfg.casing_quote_normalization_rate * n_gold)
    selected = _select(rng, len(opportunities), target)
    achieved["casing_quote_normalization"] = (sum(selected) / n_gold) if n_gold else 0.0
    hit_at = {opportunities[i] for i, hit in enumerate(selected) if hit}

    out = []
    for i, u in enumerate(units):
        if i in hit_at:
            out.append(
                _Unit(
                    text=u.text.translate(_CURLY_QUOTES),
                    gold_indices=u.gold_indices,
                    causes=u.causes | {"casing_quote_normalization"},
                )
            )
        else:
            out.append(u)
    return out, deletions


_TRANSFORMS = {
    "whole_span_deletion": whole_span_deletion,
    "false_start_deletion": false_start_deletion,
    "filler_removal": filler_removal,
    "repetition_collapse": repetition_collapse,
    "asr_name_correction": asr_name_correction,
    "contraction_expansion": contraction_expansion,
    "numeral_conversion": numeral_conversion,
    "acronym_collapse": acronym_collapse,
    "sentence_reorder": sentence_reorder,
    "editorial_insertion": editorial_insertion,
    "casing_quote_normalization": casing_quote_normalization,
}


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def _gold_hash(words: list[STTWord]) -> str:
    # Text AND timing: a re-run STT pass that reproduces identical words
    # with shifted timestamps must invalidate stored indices too.
    h = hashlib.sha256()
    for w in words:
        h.update(f"{w.text}\t{w.start}\t{w.end}\n".encode())
    return h.hexdigest()


def _config_hash(generator_version: str, transform_order: tuple[str, ...], resolved_config: dict[str, float], level: float) -> str:
    canonical = ";".join(f"{name}={round(rate, 6)}" for name, rate in sorted(resolved_config.items()))
    payload = f"{generator_version}|{','.join(transform_order)}|{canonical}|{round(level, 6)}"
    return hashlib.sha256(payload.encode()).hexdigest()


def corrupt(
    words: list[STTWord],
    level: float,
    *,
    doc_id: str,
    master_seed: int = 42,
    config: CorruptionConfig | None = None,
    transform_order: tuple[str, ...] = TRANSFORM_ORDER,
) -> CorruptedTranscript:
    """Return the artificially "human-edited" version of `words`, plus the
    mapping back to ground truth.

    `level` in [0.0, 1.0] scales every transform's rate; `level=0.0` is
    byte-identical to the input with an all-untouched mapping. `doc_id` is
    required (no default): a shared default would correlate corruption
    across every document in a corpus drawn under one `master_seed`.
    """
    cfg = config or CorruptionConfig()
    n_gold = len(words)
    resolved = cfg.resolved(level)

    units = [_Unit(text=w.text, gold_indices=(i,)) for i, w in enumerate(words)]
    deletions: list[DeletionRecord] = []
    # Every transform reads its own `*_rate` field off one shared config,
    # so build the level-scaled copy once rather than per transform.
    scaled_cfg = _scale_config(cfg, resolved)

    # What each transform actually achieved, in the same units as its own
    # rate — not just what it was asked for. `_select` silently clamps a
    # target past the available opportunity count; this makes that clamp a
    # manifest fact instead of something only visible by reading the code.
    achieved: dict[str, float] = {}
    for name in transform_order:
        rng = _rng_for(master_seed, name, doc_id)
        transform = _TRANSFORMS[name]
        units, deletions = transform(units, deletions, rng, n_gold, scaled_cfg, achieved)

    deletions.sort(key=lambda d: d.gold_start)
    logger.debug(
        "corrupt doc=%s level=%s achieved=%s",
        doc_id,
        level,
        {name: round(value, 4) for name, value in sorted(achieved.items())},
    )

    mapping = tuple(
        TokenMapping(edited_index=i, gold_indices=u.gold_indices, causes=u.causes)
        for i, u in enumerate(units)
    )
    manifest = CorruptionManifest(
        generator_version=GENERATOR_VERSION,
        master_seed=master_seed,
        doc_id=doc_id,
        level=level,
        transform_order=transform_order,
        resolved_config=tuple(sorted(resolved.items())),
        effective_config=tuple(sorted((name, achieved.get(name, 0.0)) for name in transform_order)),
        gold_hash=_gold_hash(words),
        config_hash=_config_hash(GENERATOR_VERSION, transform_order, resolved, level),
    )
    return CorruptedTranscript(
        tokens=tuple(u.text for u in units),
        mapping=mapping,
        deletions=tuple(deletions),
        manifest=manifest,
    )


def _scale_config(cfg: CorruptionConfig, resolved: dict[str, float]) -> CorruptionConfig:
    """Hand every transform a config whose rates are already level-scaled
    rather than threading `level` through every transform signature."""
    return CorruptionConfig(
        whole_span_deletion_rate=resolved["whole_span_deletion"],
        whole_span_chunk_len=cfg.whole_span_chunk_len,
        false_start_rate=resolved["false_start_deletion"],
        false_start_chunk_len=cfg.false_start_chunk_len,
        filler_removal_rate=resolved["filler_removal"],
        repetition_collapse_rate=resolved["repetition_collapse"],
        asr_name_correction_rate=resolved["asr_name_correction"],
        contraction_expansion_rate=resolved["contraction_expansion"],
        numeral_conversion_rate=resolved["numeral_conversion"],
        acronym_collapse_rate=resolved["acronym_collapse"],
        sentence_reorder_rate=resolved["sentence_reorder"],
        editorial_insertion_rate=resolved["editorial_insertion"],
        casing_quote_normalization_rate=resolved["casing_quote_normalization"],
    )
