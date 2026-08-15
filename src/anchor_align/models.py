"""Data contracts shared across every module.

These are the only shapes allowed to cross module boundaries; validation
happens here, at the edges, not three modules downstream.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

# Quantized to 1ms: interpolation accumulates float drift, which would
# otherwise surface as golden-file failures on the 15th decimal rather than
# as a real timing bug.
Seconds = Annotated[float, BeforeValidator(lambda v: round(float(v), 3)), Field(ge=0)]


class TimeSpan(BaseModel):
    """Base for every timed span.

    Frozen: spans cross module boundaries and a later stage must never
    mutate one an earlier stage still holds. `end >= start` only — STT
    engines emit start == end tokens; Cue tightens this to end > start.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: Seconds
    end: Seconds

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError(f"inverted span: start={self.start} > end={self.end}")
        return self

    @property
    def duration(self) -> Seconds:
        return self.end - self.start


class STTWord(TimeSpan):
    """A single word as produced by an STT adapter, with raw timing."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    speaker: str | None = None


class EditedToken(BaseModel):
    """A token from the human-edited transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    index: int  # ordinal position in the full edited token stream
    char_offset: int  # offset into the source document, to point an editor at it
    sentence_id: int
    is_sentence_end: bool


class NormalizedToken(BaseModel):
    """Comparable form of a token, derived without discarding the original.

    Produced independently for each stream; `source_indices` always indexes
    this token's own origin stream. `char_span` lets the exact original
    surface be reconstructed by slicing the source text (used by
    `normalize()`'s span invariant); `source_indices` is what the S1<->S2
    bridge round-trips against.

    `keys` holds candidate phonetic keys from the configured
    `PhoneticEncoder` — variadic on purpose: Double Metaphone emits two, a
    phonemic encoder one, a null encoder zero. Any key on one side matching
    any key on the other counts; an empty tuple means "no phonetic key".

    `variants` holds alternate word-sequence readings over the SAME
    `char_span` (a numeral's word-form readings, a contraction's expansion)
    — one segment node, several readings; S3 picks which scores best.

    `trailing_punct` records trailing punctuation as data rather than
    deleting it, so `char_span` stays reconstructable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    surface: str
    normal: str  # canonical comparable form
    variants: tuple[tuple[str, ...], ...] = ()  # alternate word-sequences over the same char_span
    char_span: tuple[int, int]  # [start, end) offset into the source text
    keys: tuple[str, ...] = ()
    trailing_punct: str = ""
    source_indices: tuple[int, ...]

    @model_validator(mode="after")
    def _ordered_span(self) -> Self:
        start, end = self.char_span
        if end < start:
            raise ValueError(f"inverted char_span: start={start} > end={end}")
        return self


class MatchType(StrEnum):
    ANCHOR = "anchor"
    EXACT = "exact"
    PHONETIC = "phonetic"
    FUZZY = "fuzzy"
    INTERPOLATED = "interpolated"


class AlignedWord(TimeSpan):
    """An edited-transcript token carrying timing recovered by alignment."""

    token: EditedToken
    match_type: MatchType
    confidence: float = Field(ge=0.0, le=1.0)
    speaker: str | None = None  # carried over from the matched STTWord, if any


class QCCode(StrEnum):
    CPS_EXCEEDED = "CPS_EXCEEDED"
    LINE_TOO_LONG = "LINE_TOO_LONG"
    TOO_MANY_LINES = "TOO_MANY_LINES"
    CUE_TOO_SHORT = "CUE_TOO_SHORT"
    CUE_TOO_LONG = "CUE_TOO_LONG"
    OVERLAP = "OVERLAP"
    # A block the editor moved is emitted in AUDIO order, not document
    # order — captions are a timeline format, so no valid file preserves
    # both. Always "info": a "needs human review" flag, not a defect.
    TRANSPOSED_BLOCK = "TRANSPOSED_BLOCK"
    # A candidate cue's words all landed at the same instant even after
    # duration padding declined to invent room that doesn't exist. Always
    # "error": those words have no usable timing and are dropped from cue
    # output rather than assigned a fake span.
    ZERO_DURATION_SPAN = "ZERO_DURATION_SPAN"


class Cue(TimeSpan):
    """A single VTT/SRT caption block.

    `lines` is plain text, no inline markup. `word_span` is the [start,
    end) index range into the exact AlignedWord list CueBuilder was called
    with — not an index into any other stream.

    `end > start` is enforced here, but 1ms quantization means CueBuilder
    must reject cues shorter than the platform minimum BEFORE constructing
    them: a real 1.4ms span rounds to identical start/end and would
    otherwise surface as a ValidationError far from its cause.
    """

    index: int
    lines: list[str]
    word_span: tuple[int, int]

    @model_validator(mode="after")
    def _nonzero_duration(self) -> Self:
        if self.end <= self.start:
            raise ValueError(
                f"zero/negative-duration cue: start={self.start} end={self.end} "
                "(1ms quantization can collapse a very short real span to zero — "
                "CueBuilder must enforce the platform minimum cue duration before "
                "constructing a Cue, not rely on this validator to catch it)"
            )
        return self


class QCIssue(BaseModel):
    """A single finding from the QC pass over produced cues."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: Literal["error", "warning", "info"]
    code: QCCode
    message: str
    cue_index: int | None = None


class EditRelation(StrEnum):
    """Reporting label derived from a TokenMapping, never stored: `causes`
    is purely additive, while MERGE/SPLIT are properties of the final
    mapping that an additive field would duplicate with an overwrite-vs-
    accumulate rule."""

    IDENTITY = "identity"  # empty causes, single unshared gold index
    SUBSTITUTE = "substitute"  # non-empty causes, single unshared gold index
    SPLIT = "split"  # single gold index, shared with another edited token
    MERGE = "merge"  # more than one gold index
    INSERTED = "inserted"  # no gold index at all — no spoken source


class TokenMapping(BaseModel):
    """One edited-stream token's provenance back to gold STTWord indices.

    `causes` unions transform names across the whole S1 pipeline — purely
    additive, never overwritten — so per-failure-mode reporting can ask
    "how did the aligner do on tokens numeral_conversion touched" without
    conflating it with acronym_collapse.

    Index-based by design: S1's corruptor generates the edited stream
    itself, so its indices are authoritative. S2 ingests a real .docx where
    the only reliable anchor is a char offset (see
    `EditedToken.char_offset`); bridging the two representations is one
    explicit adapter's job, not an implicit assumption that they line up.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    edited_index: int
    gold_indices: tuple[int, ...]  # empty iff this token has no spoken source
    causes: frozenset[str] = frozenset()


def _classify_one(entry: TokenMapping, gold_index_counts: Counter[int]) -> EditRelation:
    if not entry.gold_indices:
        return EditRelation.INSERTED
    if len(entry.gold_indices) > 1:
        return EditRelation.MERGE
    if gold_index_counts[entry.gold_indices[0]] > 1:
        return EditRelation.SPLIT
    return EditRelation.SUBSTITUTE if entry.causes else EditRelation.IDENTITY


def classify_all(mapping: tuple[TokenMapping, ...]) -> tuple[EditRelation, ...]:
    """Classify every entry in one pass: SPLIT needs to know whether a gold
    index recurs across entries, which a per-entry scan would make
    quadratic."""
    gold_index_counts = Counter(gi for entry in mapping for gi in entry.gold_indices)
    return tuple(_classify_one(entry, gold_index_counts) for entry in mapping)


def classify(entry: TokenMapping, mapping: tuple[TokenMapping, ...]) -> EditRelation:
    """Single-entry convenience wrapper. O(n) per call — use `classify_all`
    for more than one entry from the same mapping."""
    gold_index_counts = Counter(gi for e in mapping for gi in e.gold_indices)
    return _classify_one(entry, gold_index_counts)


def non_monotonic_pair_fraction(mapping: tuple[TokenMapping, ...]) -> float:
    """Fraction of adjacent (by edited_index) gold-index pairs that go
    backwards. Derived from the mapping rather than tagged per-token:
    reordering is a property of the sequence, not of a token."""
    flat = [gi for entry in mapping for gi in entry.gold_indices]
    if len(flat) < 2:
        return 0.0
    backward = sum(1 for a, b in pairwise(flat) if b < a)
    return backward / (len(flat) - 1)


class DeletionRecord(BaseModel):
    """A contiguous run of gold words removed with no surviving edited
    token, and why. Recorded explicitly rather than inferred from missing
    gold indices: a filler cut and a tangent cut are different failure
    modes inference can't tell apart after the fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gold_start: int  # inclusive
    gold_end: int  # exclusive
    cause: str  # transform name that made the cut


class CorruptionManifest(BaseModel):
    """Identity of one S1-generated corpus, for dataset versioning.

    Bump `generator_version` on any transform-logic change; `config_hash`
    catches config drift; `gold_hash` catches the gold sequence changing.
    `gold_hash` MUST cover (text, start, end) for every gold word — a
    re-run reproducing identical words with shifted timestamps has to
    invalidate stored indices too, since timing is what's benchmarked.

    `resolved_config` is what was REQUESTED (rate * level per transform);
    `effective_config` is what was ACHIEVED — `_select` silently clamps a
    target past its opportunity count, and without the achieved rates that
    clamp is invisible. effective < resolved is the healthy case; equality
    at the ceiling usually means the transform is saturated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    generator_version: str
    master_seed: int
    doc_id: str
    level: float
    transform_order: tuple[str, ...]
    resolved_config: tuple[tuple[str, float], ...]
    effective_config: tuple[tuple[str, float], ...]
    gold_hash: str
    config_hash: str


class CorruptedTranscript(BaseModel):
    """Full output of one S1 corruption run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tokens: tuple[str, ...]
    mapping: tuple[TokenMapping, ...]  # mapping[i].edited_index == i
    deletions: tuple[DeletionRecord, ...]  # sorted by gold_start
    manifest: CorruptionManifest


class STTOptions(BaseModel):
    """Vendor-agnostic options passed to an STTProvider; an adapter
    translates these into its own API's parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    keyterms: list[str] = Field(default_factory=list)
    language: str | None = None
    diarize: bool = False


class Transcription(BaseModel):
    """Full output of one STT pass: words plus the metadata needed for
    cache keys and reproducibility."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    words: list[STTWord]
    model_id: str
    audio_duration: Seconds
    language: str | None = None


class AlignmentMetrics(BaseModel):
    """What S3 is optimized against, and what S4 measures per corruption
    level against S1 ground truth.

    Boundary error is (predicted - ground_truth) in ms for start and end of
    every AlignedWord. The absolute mean captures magnitude; the signed
    mean exposes systematic offset (uniformly 40ms late vs. randomly ±40ms
    score identically on the absolute mean). p95 uses numpy.percentile's
    'linear' method — naming the estimator matters because methods disagree
    by a few ms on small samples.

    `measured_word_count` is the sample behind mean/p95 and is NOT
    `word_count`: interpolated words have no reference timing to score, so
    error stats cover the anchor/exact/phonetic/fuzzy subset only.

    `match_type_counts` stores counts, not a distribution: three ratios as
    count/total won't sum to exactly 1.0 in binary float. The derived
    distribution's denominator is the full word_count.

    MFA's sub-15ms figure is acoustic phone-boundary error against
    hand-annotated corpora — a different measurement; treat it as an
    order-of-magnitude reference, not a target.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mean_abs_boundary_error_ms: float = Field(ge=0.0)
    mean_signed_boundary_error_ms: float
    p95_abs_boundary_error_ms: float = Field(ge=0.0)
    measured_word_count: int = Field(ge=1)
    match_type_counts: dict[MatchType, Annotated[int, Field(ge=0)]]

    @model_validator(mode="after")
    def _at_least_one_word(self) -> Self:
        if sum(self.match_type_counts.values()) < 1:
            raise ValueError(
                "match_type_counts sums to zero words aligned — compute_metrics "
                "must handle the empty-alignment case explicitly rather than "
                "constructing an AlignmentMetrics with an undefined mean/p95"
            )
        return self

    @model_validator(mode="after")
    def _measured_subset_of_all(self) -> Self:
        if self.measured_word_count > self.word_count:
            raise ValueError(
                f"measured_word_count ({self.measured_word_count}) exceeds "
                f"word_count ({self.word_count}) — the error-scored subset "
                "can't be larger than the full alignment"
            )
        return self

    @property
    def word_count(self) -> int:
        return sum(self.match_type_counts.values())

    @property
    def match_type_distribution(self) -> dict[MatchType, float]:
        total = self.word_count
        return {k: v / total for k, v in self.match_type_counts.items()}


class BenchmarkRow(BaseModel):
    """One row of S4's results table: an AlignmentMetrics plus the exact
    S1 corruption run it was measured against.

    `config_hash` and `master_seed` are typed fields, not a convention: a
    result with no way to identify which CorruptionConfig produced it
    becomes unusable the first time the config gets tuned. `doc_id` is
    required for the same reason — config_hash encodes the RECIPE, which
    is identical across documents, so without doc_id two rows from
    different documents would be indistinguishable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aligner_name: str
    level: float
    master_seed: int
    config_hash: str
    doc_id: str
    metrics: AlignmentMetrics


class DriftMetrics(BaseModel):
    """Does boundary error grow over a document's length, or stay bounded?

    A pooled mean can't answer this: a method whose error grows linearly
    toward the end and one with uniformly-high error average to the same
    number while describing different failure modes — exactly what "does
    it still line up by minute 40" means, and exactly what periodic
    re-anchoring is supposed to bound.

    `body` is the first `1 - tail_fraction` of the document's TIMELINE
    (not token count — a document isn't corrupted evenly per token), `tail`
    the final `tail_fraction`, both computed from each scored word's TRUE
    (gold) start time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    body_mean_abs_error_ms: float = Field(ge=0.0)
    body_max_abs_error_ms: float = Field(ge=0.0)
    body_measured_count: int = Field(ge=1)

    tail_mean_abs_error_ms: float = Field(ge=0.0)
    tail_max_abs_error_ms: float = Field(ge=0.0)
    tail_measured_count: int = Field(ge=1)

    @property
    def tail_minus_body_mean_abs_error_ms(self) -> float:
        """Positive means error grows toward the end of the document — the
        cumulative-drift signature."""
        return self.tail_mean_abs_error_ms - self.body_mean_abs_error_ms


class ReorderTouch(StrEnum):
    """Which bucket a DriftBenchmarkRow was scored on. A closed enum makes
    a typo'd third variant a hard error instead of silently splitting one
    bucket into two, in Python AND in the Polars frame run_benchmark
    writes (pl.Enum).

    NOT_TOUCHED is deliberately not called "clean": it means "this token
    was not itself edited by sentence_reorder", not "this token's timing
    is independent of reordering elsewhere" — drift propagates downstream
    of where it originates, so same-document independence does NOT hold.
    """

    TOUCHED = "touched_by_reorder"
    NOT_TOUCHED = "not_touched_by_reorder"


class DriftBenchmarkRow(BaseModel):
    """One row of the drift comparison: a DriftMetrics plus which
    ReorderTouch bucket it was computed over, and the exact S1 run it was
    measured against — same identity-field discipline as BenchmarkRow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aligner_name: str
    level: float
    master_seed: int
    config_hash: str
    doc_id: str
    bucket: ReorderTouch
    drift: DriftMetrics
