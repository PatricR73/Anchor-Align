# Design decisions

The decisions below were reached the hard way — each one is a fix for a
bug or a measured failure, not a preference. Read this before changing
anything in the pipeline.

## Interpolation happens exactly once, at the point of production

`align()` resolves every unmatched word's timing inside the segment that
produced it (`_dp_segment`), bounded by that segment's own real anchor
timestamps. There is no final document-wide `interpolate_gaps()` pass, and
there must never be one: there is no signal on an `AlignedWord` for
"already resolved locally" vs "still a raw placeholder", so a global pass
would silently re-interpolate every resolved word using flat cross-chain
neighbors and undo segment-local correctness. This was a real bug, found
by testing — the first version of `align()` ended in
`return interpolate_gaps(aligned)` and every local resolution was
overwritten.

## Captions are emitted in audio order, not document order — always

A caption file's cue order *is* its timeline. When an editor moves a
block, there is no valid VTT that preserves both the document order and
the audio timeline. `resolve_audio_order` sorts align()'s output by true
timestamp and emits one `TRANSPOSED_BLOCK` issue (info severity — a
"needs human review" flag, not a defect) per relocated span. Every
downstream consumer — `segment_into_cues`, `qc_report` — raises on input
that skips this step, rather than silently producing wrong output.

## Segment-node, not lattice, for ambiguous readings

A numeral span ("2024") is ONE `NormalizedToken` (one `char_span`,
atomic) carrying every plausible word-sequence reading in `variants`
("twenty twenty four", "two thousand twenty four"). This keeps S3's DP
over a flat sequence while S3 still picks which reading scores best — S2
generates every reading, S3 never derives them. Same mechanism for
contractions ("don't" -> "do" + "not" as a variant reading). The
alternative (a DAG) would ripple into every stage of S3 for no measured
benefit.

## S1's corruption generator is pinned, hard

- **Never diff at the end.** Each transform threads the same `_Unit`
  records through the pipeline, unioning provenance into `causes` — never
  reconstructing alignment afterwards, which would silently reintroduce
  the exact problem the module exists to benchmark.
- **Never touch the global `random` module.** Every transform draws from
  its own `random.Random` seeded from `(master_seed, transform_name,
  doc_id)`, independent of level and of every other transform — so adding
  or tuning one transform cannot perturb another's draws.
- **Draw-then-threshold sampling** makes low levels strict subsets of
  high levels for a transform run in isolation.
- **`level=0.0` is byte-identical to the input** with an all-untouched
  mapping — the decisive sanity check every benchmark depends on.
- A golden test pins the exact output at one (seed, doc, level); any
  transform-logic change must bump `GENERATOR_VERSION` and regenerate the
  pinned constants deliberately.

## The caption limits live in one module

`caption_constraints.py` is the single source for the 2-line / 42-char /
1-7s / 21-cps limits, imported by both segmentation (S5) and QC (S8). A
consistency test asserts they cannot drift apart — QC must never flag what
the segmenter already guarantees, or miss what it doesn't.

## Phonetic matching is opt-in, by measurement

`DoubleMetaphoneEncoder` is implemented and reachable via
`align(..., phonetic_encoder=...)` / CLI `--phonetic`, but the default is
no phonetic matching. Wiring it in as the default regressed the synthetic
corpus — short common words collide on Double Metaphone keys
(`and`/`end` -> `ANT`) and, inside the force-aligned spans of unrecovered
reorders, those collisions become confident long-distance mismatches
(worst case 6.6s -> 13.4s). The synthetic corpus has no genuine homophone
edits, so the feature only fired on false collisions, and no threshold
can separate a false collision from a true homophone — they score
identically. The full measurement is in [BENCHMARKS.md](BENCHMARKS.md).
Enable it for real transcripts where ASR mishearings are common, and
re-benchmark against your own data.

## S1 and S2 mapping representations are deliberately separate

S1's `TokenMapping` is index-based (the corruptor generates the edited
stream, so its indices are authoritative). S2's `EditedToken` carries
`char_offset` into a real source document. Unifying them would force
either S1 to carry spans it doesn't need or every S1 test to tolerate
fuzzier equality. Bridging is one explicit adapter's job, guarded by an
xfail test that forces the round-trip assertion to be written when the
adapter lands.

## Error handling and logging

- Pipeline failures carry context and are catchable by type:
  `AnchorAlignError` -> `IngestError` / `TranscriptionError`. Both
  inherit `RuntimeError` so callers written against the old bare
  `RuntimeError` raises keep working.
- Input-contract violations (unsorted input, mismatched lengths) stay
  plain `ValueError` — those are programming errors, not pipeline
  failures, and every stage checks them at its own boundary rather than
  trusting the caller.
- Library modules create loggers but never configure handlers; entry
  points (CLI, demo) call `configure_logging` once.
- Transcriptions are disk-cached keyed on audio *content* (not path), the
  adapter name, and the options — renames and re-runs hit the cache,
  different models never collide.

## Reproducibility

`uv.lock` is committed; CI installs with `uv sync --frozen`. The benchmark
parquet tables and charts in `benchmarks/results/` are regenerable with
`run_benchmark`, and every result row carries `config_hash`/`master_seed`/
`doc_id` so a score can always be traced to the exact corruption run that
produced it.

## Confidence is encoded twice — color AND solidity (web UI)

Every confidence visual in the web UI carries a *second, color-independent*
channel, and that channel is not decoration: it exists because the color
ramp alone fails for a large share of users, measured, not guessed.

- The ramp runs red -> amber -> phosphor along the red-green confusion
  axis. Simulated under deuteranopia (Machado matrices, in
  `web/ui/src/lib/colors.ts`), the mid-amber and high-green bands collapse
  in luminance (dL 0.016); under protanopia the red/green hue distinction
  vanishes outright. Grayscale loses the hue entirely. "Look at the red
  words" therefore excludes deuteranopes, protanopes, and grayscale
  contexts, and the numbers above are why the second channel exists.
- The second channel encodes *solidity*: lower confidence is rendered
  thinner (font weight 400..650) in the heatmap and shorter (bar height
  25%..100%) in the timeline. Both derive from the same `confidenceSolidity`
  function in `colors.ts`, so the channels share one source of truth and
  cannot drift apart. The mapping is monotonic (more solid = more
  confident), which implies no false ordering between words.
- Do NOT revert this channel as "visual noise". A patch that removes the
  font-weight/height encoding to clean up the visuals removes the only
  confidence signal a deuteranope or a grayscale reader has. If the look
  needs changing, change the ramp or the encoding — not the redundancy.
- CI guards the encoding structurally: `probe-color.mjs` verifies the
  dichromacy luminance separation under simulation, and the P1
  `timeline-widths.mjs` check keeps the height encoding from breaking the
  segment-width invariant (a width regression would hide the height
  channel by overflowing the strip).
