# Benchmarks

Every number on this page comes from a synthetic corruption model —
`corrupt/corruptor.py` turns ground-truth (word, timing) pairs into an
artificially "human-edited" version plus the mapping back to ground truth,
across 11 edit transforms (filler removal, contraction expansion, name
correction, sentence reorder, ...). The corpus is `corrupt/corpus.py`:
20 synthetic documents with jittered per-word durations and real
sentence-boundary pauses, generated deterministically from a seed.

**Read this before quoting any number here:** the base rates in
`CorruptionConfig` are calibrated by feel, not against a measured
distribution of real edits. Two things remain unmeasured until real data
exists:

- **Gold timing noise.** STT timestamps carry their own error, worst on
  disfluencies — exactly the things `filler_removal` and
  `repetition_collapse` target. Without a hand-labeled sample, no
  measured improvement has a known noise floor.
- **Real edit distribution.** No held-out set of real (raw transcript,
  published edited transcript) pairs exists yet. Until it does, all of
  the following is directional.

The whole page is regenerable: the benchmark tests print these tables via
`pytest -s tests/benchmark`, and `run_benchmark` writes the parquet
tables and the charts in `benchmarks/results/`.

## Boundary error vs corruption level (20-document corpus)

`compute_metrics` scores predicted boundaries against S1 ground truth:
mean absolute and signed error in milliseconds, p95, and the fraction of
words matched exactly / left interpolated.

**Baseline (`difflib.SequenceMatcher`):**

| level | mean abs (ms) | mean signed (ms) | p95 (ms) | exact | interpolated |
|---|---|---|---|---|---|
| 0.0 | 0.0 | +0.0 | 0.0 | 1.000 | 0.000 |
| 0.1 | 2.8 | -1.5 | 0.0 | 0.922 | 0.078 |
| 0.3 | 162.3 | -14.6 | 331.3 | 0.851 | 0.149 |
| 0.5 | 336.8 | -95.9 | 628.6 | 0.737 | 0.263 |

**Real aligner vs baseline:**

| level | real mean abs (ms) | baseline mean abs (ms) | real exact+anchor | real interpolated |
|---|---|---|---|---|
| 0.0 | 0.0 | 0.0 | 1.000 | 0.000 |
| 0.1 | 2.4 | 2.8 | 0.939 | 0.060 |
| 0.3 | 155.9 | 162.3 | 0.896 | 0.104 |
| 0.5 | 298.4 | 336.8 | 0.826 | 0.174 |

On mean accuracy alone the two methods are close — both compute a
monotone alignment path, so they fail identically on anything a monotone
path can't represent. They diverge on the two things that matter for a
real transcript: drift over a long file, and recovery from whole-block
relocation.

## Drift: does timing still line up by minute 40?

`compute_drift` splits a document's *timeline* (not token count) into the
first 90% ("body") and final 10% ("tail"), over 8 synthetic long
documents (~4000 words each). Reported here for tokens NOT themselves
touched by a reorder edit.

| level | aligner | body mean (ms) | tail mean (ms) |
|---|---|---|---|
| 0.1 | real | 9.3 | 4.2 |
| 0.1 | baseline | 43.7 | 22.1 |
| 0.3 | real | 7.3 | 4.0 |
| 0.3 | baseline | 120.5 | **370.9** |

At level 0.3 the baseline's tail error is 3x its own body error — the
textbook cumulative-drift signature of a method with no way to
re-establish its position partway through a file. The real aligner's tail
error never exceeds its body error at either level: periodic re-anchoring
is doing what it's for.

Caveat, load-bearing: "not touched by a reorder" means *this token* wasn't
edited by a reorder — not that its document is clean. Drift propagates
downstream of where it originates, so untouched tokens can still inherit
error from an earlier reorder the aligner mishandled. The two buckets are
not statistically independent.

## Whole-block relocation

When `sentence_reorder` swaps two sentences, the true correspondence for
that span is non-monotonic. `find_anchors` excludes anchors from both
sides of the swap — keeping them would require a non-monotonic path —
leaving one large unanchored segment that a sequential DP force-aligns
positionally. Fixed with **anchor chaining** (`anchors.find_displaced_blocks`,
the standard genome-alignment technique): the backbone-excluded residual
is LIS-chained again; a residual chain of length >= 3 that is internally
monotonic in both streams is a displaced block, DP-aligned independently
against its own true span.

Pooled worst-case boundary error (ms), documents containing a reorder,
corpus seed 1 / corruption seed 1:

| level | real max (ms) | baseline max (ms) |
|---|---|---|
| 0.3 | 6708 | 7286 |
| 0.5 | 6708 | 20540 |

Where a block is recovered, boundary error on its tokens is exactly 0.0ms
— verified directly, including ordinary short words between the anchor
points. **That 0.0 is a property of the corruption model, not a general
claim about reordering**: S1 relocates a block's text verbatim, so once
the DP's window is correctly bounded, its interior job is trivial. A human
editor moving a paragraph typically rewrites its seams; when the interior
isn't identical, 0.0 does not hold. The honest statement is: *when a
relocated block's content is unchanged, correct segmentation recovers its
timing exactly.*

Chains shorter than 3 anchors are not recovered, by construction; those
spans fall through to pre-chaining behavior, and the remaining multi-second
cases there are a named, open gap.

## Resolved default rates (fraction of n_gold, at level=1.0)

| transform | base rate | notes |
|---|---|---|
| whole_span_deletion | 0.06 | chunked, ~20-token cuts |
| false_start_deletion | 0.06 | chunked, ~3-token cuts |
| filler_removal | 0.5 | |
| repetition_collapse | 0.7 | MERGE, not deletion |
| asr_name_correction | 0.7 | SUBSTITUTE |
| contraction_expansion | 0.7 | SPLIT |
| numeral_conversion | 0.7 | MERGE |
| acronym_collapse | 0.7 | MERGE |
| sentence_reorder | 3.0/100 tokens | swaps per 100 gold tokens |
| editorial_insertion | 0.03 | INSERTED, no gold source |
| casing_quote_normalization | 0.5 | |

These rates define what "level 0.3" means; changing them silently
redefines the x-axis of every chart. The pinned golden test in
`tests/corrupt/test_corruptor.py` enforces that any logic change bumps
`GENERATOR_VERSION`.

## The phonetic experiment (and why it is opt-in)

The aligner's substitution scoring blends edit distance with phonetic key
overlap (`MatchType.PHONETIC`). For a long time the phonetic half was
unreachable because the aligner hardcoded a null encoder. This repo now
implements `DoubleMetaphoneEncoder` and exposes it as an `align()` /
CLI `--phonetic` parameter — and it is **off by default, by measurement**:

- With Double Metaphone live, mean boundary error *rose* at every level
  on the corpus (0.1: 2.4 -> 2.9ms; 0.3: 155.9 -> 169.9ms; 0.5: 298.4 ->
  315.6ms) and worst-case error *doubled* (6.6s -> 13.4s).
- Cause: short common words collide on phonetic keys (`and`/`end` both ->
  `ANT`), and inside the force-aligned spans of unrecovered reorders the
  DP turns those collisions into confident long-distance mismatches —
  worse than an honest gap. The synthetic corpus contains no genuine
  homophone edits, so the feature only fires on false collisions.
- No threshold re-tune can separate the false case from a true one:
  `and`<->`end` and `frayed`<->`frade` score identically under every
  weighting. The distinction is spatial, not lexical.

Enable `--phonetic` (or `phonetic_encoder=DoubleMetaphoneEncoder()`) on
real transcripts where homophone mishearings are common, and benchmark it
against your own data. The day the spatial fix lands — a repair strategy
for the unrecovered-span gap — phonetic matching likely becomes safe to
default on.
