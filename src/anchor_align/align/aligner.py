"""S3 — orchestrator: the alignment engine's public entry point.

Pure function, zero dependency on audio or the filesystem. Two word lists
in, one mapping with a per-word confidence score out. Composes S3a -> S3b
-> S3c.
"""

from __future__ import annotations

import logging
from itertools import pairwise

from anchor_align.align.anchors import find_displaced_blocks
from anchor_align.align.interpolate import interpolate_gaps
from anchor_align.align.needleman_wunsch import align_segment
from anchor_align.interfaces import PhoneticEncoder
from anchor_align.models import (
    AlignedWord,
    EditedToken,
    MatchType,
    NormalizedToken,
    QCCode,
    QCIssue,
    STTWord,
)
from anchor_align.normalize.normalizer import (
    NullEncoder,
    apply_phonetic_encoder,
    casefold_and_ascii_fold,
    expand_contractions,
    expand_numerals,
    extract_trailing_punct,
    fold_unicode,
)

logger = logging.getLogger(__name__)

# Module-level singleton so the default-argument evaluation happens once.
# NullEncoder by default: DoubleMetaphoneEncoder is implemented, reachable
# and tested, but benchmarked as a regression on the synthetic corpus —
# short common words collide on phonetic keys (and/end -> ANT) inside the
# force-aligned spans of unrecovered reorders, creating confident long-
# distance mismatches. Opt in for real transcripts where homophone edits
# (ASR mishearings) are common: align(..., phonetic_encoder=DoubleMetaphoneEncoder()).
_DEFAULT_PHONETIC_ENCODER = NullEncoder()

_CONFIDENCE_BY_MATCH_TYPE = {
    MatchType.ANCHOR: 1.0,
    MatchType.EXACT: 0.95,
    MatchType.PHONETIC: 0.7,
    MatchType.FUZZY: 0.5,
    MatchType.INTERPOLATED: 0.0,
}


def _seed_normalized_tokens(texts: list[str]) -> list[NormalizedToken]:
    """Build initial NormalizedTokens directly from an already-tokenized
    word stream rather than via `normalize_tokens`, which re-tokenizes a
    raw string by whitespace — wrong here, since these streams are already
    tokenized one word at a time. `char_span` is a synthetic cumulative
    offset: no single real source string exists to slice, and nothing
    downstream dereferences it (only S2's own span invariant does, and it
    is never called on these synthetic spans)."""
    tokens = []
    offset = 0
    for i, text in enumerate(texts):
        tokens.append(
            NormalizedToken(surface=text, normal=text, char_span=(offset, offset + len(text)), source_indices=(i,))
        )
        offset += len(text) + 1
    return tokens


def normalize_for_alignment(
    texts: list[str], *, phonetic_encoder: PhoneticEncoder = _DEFAULT_PHONETIC_ENCODER
) -> list[NormalizedToken]:
    """Run S2's steps 2-7 (fold/punct/case/phonetic/contractions/numerals)
    over an already-tokenized word stream, skipping the whitespace
    tokenizer (see `_seed_normalized_tokens`). The phonetic step defaults
    to `NullEncoder`; pass `DoubleMetaphoneEncoder()` to enable phonetic
    matching (see `align`'s docstring for why it is opt-in).
    """
    tokens = _seed_normalized_tokens(texts)
    tokens = fold_unicode(tokens)
    tokens = extract_trailing_punct(tokens)
    tokens = casefold_and_ascii_fold(tokens)
    tokens = apply_phonetic_encoder(tokens, phonetic_encoder)
    tokens = expand_contractions(tokens)
    tokens = expand_numerals(tokens)
    return tokens


def _readings(token: NormalizedToken) -> set[str]:
    return {token.normal, *(" ".join(v) for v in token.variants)}


def _classify_match(stt_tok: NormalizedToken, edited_tok: NormalizedToken) -> MatchType:
    """EXACT if any reading on either side matches exactly (a variant
    reading is still an exact textual match, just of an alternate form).
    PHONETIC if no textual reading matched but a phonetic key did. FUZZY
    otherwise — S3b matched them via edit-distance similarity alone."""
    if _readings(stt_tok) & _readings(edited_tok):
        return MatchType.EXACT
    if stt_tok.keys and edited_tok.keys and set(stt_tok.keys) & set(edited_tok.keys):
        return MatchType.PHONETIC
    return MatchType.FUZZY


def _repair_variant_merges(
    pairs: list[tuple[int | None, int | None]],
    stt_seg: list[NormalizedToken],
    edited_seg: list[NormalizedToken],
) -> tuple[list[tuple[int | None, int | None]], dict[int, tuple[int, int]]]:
    """S3b's DP is pairwise (one stt token per edited token); it cannot by
    itself represent "one edited token's variant reading spans several gold
    tokens" (a numeral like '20%' whose reading is 'twenty percent', or a
    contraction's two-word expansion). Left alone, the DP either emits a
    run of gold deletions next to an unrelated edited insertion, or folds
    ONE gold word into a substitution and leaves the rest as deletions.
    Both shapes are repaired here: for every pairs entry with an edited
    index, try growing it with immediately-adjacent gold deletions on both
    sides; if the joined gold text exactly equals one of the edited token's
    readings, merge them into a single (stt_start, stt_end) span.

    Returns (leftover pairs with merged entries removed, {local_edited_index:
    (stt_start, stt_end)}). Local indices — the caller offsets them into
    the full streams.

    Known gap: only adjacent-in-traceback-order runs are considered, not
    every possible interleaving. Real editing rarely scrambles a numeral's
    two gold words apart from each other, so this covers the common case.
    """
    consumed: set[int] = set()
    merged_stt_runs: dict[int, tuple[int, int]] = {}

    def _deletion_run(start_idx: int, step: int) -> list[tuple[int, int]]:
        """(index_in_pairs, stt_index) for each deletion in a maximal run
        stepping away from start_idx — carrying the already-narrowed stt
        index alongside its pairs-index so callers never re-index `pairs`
        and lose the non-None guarantee this loop established."""
        run: list[tuple[int, int]] = []
        idx = start_idx + step
        while 0 <= idx < len(pairs) and idx not in consumed:
            stt_at_idx, edited_at_idx = pairs[idx]
            if edited_at_idx is not None or stt_at_idx is None:
                break
            run.append((idx, stt_at_idx))
            idx += step
        if step < 0:
            run.reverse()
        return run

    for k, (stt_i, j) in enumerate(pairs):
        if j is None or k in consumed:
            continue
        edited_tok = edited_seg[j]
        if not edited_tok.variants:
            continue

        before = _deletion_run(k, -1)
        after = _deletion_run(k, 1)
        stt_positions: list[int] = (
            [v for _, v in before] + ([stt_i] if stt_i is not None else []) + [v for _, v in after]
        )
        if not stt_positions:
            continue

        gold_text = " ".join(stt_seg[p].normal for p in stt_positions)
        if gold_text not in _readings(edited_tok):
            continue

        merged_stt_runs[j] = (stt_positions[0], stt_positions[-1])
        consumed.add(k)
        consumed.update(idx for idx, _ in before)
        consumed.update(idx for idx, _ in after)

    leftover = [p for idx, p in enumerate(pairs) if idx not in consumed]
    return leftover, merged_stt_runs


_START_GROUP = "start"
_BACKBONE_GROUP = "backbone"
_END_GROUP = "end"


def _group_compatible(prev_group: str | int, next_group: str | int) -> bool:
    """Two consecutive anchor-chain entries (backbone or displaced-block,
    tagged by group) are only safe to DP-align between if they're the SAME
    chain. Crossing a group boundary means the simple (prev.stt+1, next.stt)
    range is not trustworthy: a displaced block's whole point is that its
    true STT range sits somewhere OTHER than "between its neighbors in
    edited order", so a segment spanning two chains would silently
    re-include content another chain already claims. The start/end
    sentinels are only compatible with the backbone, conservatively
    applied at the document edges too.
    """
    if prev_group == _START_GROUP:
        return next_group == _BACKBONE_GROUP
    if next_group == _END_GROUP:
        return prev_group == _BACKBONE_GROUP
    return prev_group == next_group


def _boundary_word(stt_word: STTWord, dummy_token: EditedToken) -> AlignedWord:
    """A synthetic AlignedWord carrying a segment's real bounding
    timestamp, for `interpolate_gaps` to anchor against — never included
    in a segment's returned output, only a temporary left/right fence so
    interpolation inside `_dp_segment` sees a real boundary instead of the
    edge of the list. The dummy token is never inspected (interpolate_gaps
    only reads start/end/match_type) and is stripped before returning."""
    return AlignedWord(
        token=dummy_token, start=stt_word.start, end=stt_word.end, match_type=MatchType.ANCHOR, confidence=1.0,
        speaker=stt_word.speaker,
    )


def _dp_segment(
    stt_norm: list[NormalizedToken],
    edited_norm: list[NormalizedToken],
    stt_words: list[STTWord],
    edited_tokens: list[EditedToken],
    prev_stt: int,
    prev_edited: int,
    next_stt: int,
    next_edited: int,
) -> list[AlignedWord]:
    """Run S3b + the variant-merge repair over one safe (same-chain)
    segment, offsetting local indices back into the full streams, and
    resolve every INTERPOLATED placeholder THIS SEGMENT'S OWN DP couldn't
    match — bounded by this segment's own real anchor timestamps
    (`stt_words[prev_stt]`/`stt_words[next_stt]`), never a different
    chain's content.

    This is what makes interpolation audio-order-correct: within one chain,
    edited order and audio order are the SAME sequence by construction (a
    chain is strictly increasing in STT index), so a segment's local
    neighbors ARE its true temporal neighbors. Resolving gaps here, before
    they reach the flat cross-chain list `align` assembles, means an
    interpolated word can never inherit a span bridging two positions that
    are adjacent in the document but seconds apart in the audio.
    """
    stt_seg = stt_norm[prev_stt + 1 : next_stt]
    edited_seg = edited_norm[prev_edited + 1 : next_edited]

    local_pairs = align_segment(stt_seg, edited_seg)
    local_pairs, merged_runs = _repair_variant_merges(local_pairs, stt_seg, edited_seg)

    raw: list[tuple[tuple[int, int] | None, int, MatchType]] = []
    for merged_local_edited, (run_start, run_end) in merged_runs.items():
        merged_global_edited = prev_edited + 1 + merged_local_edited
        merged_span = (prev_stt + 1 + run_start, prev_stt + 1 + run_end)
        raw.append((merged_span, merged_global_edited, MatchType.EXACT))
    for local_stt, local_edited in local_pairs:
        if local_edited is None:
            continue  # a gold word with no edited counterpart at all
        global_edited = prev_edited + 1 + local_edited
        if local_stt is None:
            raw.append((None, global_edited, MatchType.INTERPOLATED))
        else:
            global_stt = prev_stt + 1 + local_stt
            match_type = _classify_match(stt_norm[global_stt], edited_norm[global_edited])
            raw.append(((global_stt, global_stt), global_edited, match_type))

    if not raw:
        return []
    raw.sort(key=lambda e: e[1])

    built: list[AlignedWord] = []
    for span, edited_i, match_type in raw:
        token = edited_tokens[edited_i]
        if span is None:
            built.append(AlignedWord(token=token, start=0.0, end=0.0, match_type=MatchType.INTERPOLATED, confidence=0.0))
        else:
            start_i, end_i = span
            start_word, end_word = stt_words[start_i], stt_words[end_i]
            built.append(
                AlignedWord(
                    token=token,
                    start=start_word.start,
                    end=end_word.end,
                    match_type=match_type,
                    confidence=_CONFIDENCE_BY_MATCH_TYPE[match_type],
                    speaker=start_word.speaker,
                )
            )

    # Fence with this segment's own real bounding anchors where they exist
    # — absent only at the very start/end of the document (prev_stt == -1 /
    # next_stt == len(stt_words), the sentinels), where interpolate_gaps
    # degrades correctly to "no neighbor on that side" on its own.
    dummy_token = edited_tokens[0]
    left = [_boundary_word(stt_words[prev_stt], dummy_token)] if 0 <= prev_stt < len(stt_words) else []
    right = [_boundary_word(stt_words[next_stt], dummy_token)] if 0 <= next_stt < len(stt_words) else []

    resolved = interpolate_gaps(left + built + right)
    return resolved[len(left) : len(resolved) - len(right)]


def align(
    stt_words: list[STTWord],
    edited_tokens: list[EditedToken],
    *,
    phonetic_encoder: PhoneticEncoder | None = None,
) -> list[AlignedWord]:
    """Align an edited transcript to STT word timing. One `AlignedWord` per
    `edited_tokens` entry, in the same order, always — including entries
    with no real evidence (`match_type=INTERPOLATED`, timing filled in by
    S3c from surrounding matches).

    Anchor chaining (see anchors.find_displaced_blocks): besides the
    backbone anchor chain, a whole relocated span can surface as its own
    DISPLACED BLOCK — internally ordered but excluded from the backbone for
    crossing it. Each block gets its own local segments, DP'd against ITS
    OWN correct STT range, so its words carry the timing of where that
    content was actually spoken. The segment at every boundary where the
    chain changes (backbone -> block, block -> block, block -> backbone, or
    a sentinel edge) is deliberately NOT DP'd: the simple (prev.stt+1,
    next.stt) range assumption breaks exactly at those crossings, so those
    edited tokens are left to interpolation instead of a bound that would
    silently re-claim another chain's STT content.

    `phonetic_encoder` selects the phonetic-key strategy for the S2 step.
    Defaults to `NullEncoder`; pass `DoubleMetaphoneEncoder()` to let
    phonetic key overlap contribute to substitution scoring (useful for
    real transcripts with homophone mishearings, and measured as a
    regression on the synthetic corpus — see BENCHMARKS.md).

    Interpolation happens IN AUDIO ORDER, not edited order: each compatible
    segment's own INTERPOLATED placeholders are resolved inside
    `_dp_segment`, bounded by that segment's own real anchors. Only
    genuinely orphaned tokens (from an incompatible chain-boundary
    crossing, belonging to no chain at all) reach the final global
    `interpolate_gaps` call, resolved against whatever real neighbors
    flank them.

    This split exists because interpolating in edited order is wrong once
    chaining exists: an edited-order-adjacent "neighbor" can be seconds
    away in the audio if a displaced block sits between them in time but
    not in the document, and an interpolated word bounded by two such
    neighbors can inherit a span wide enough to overlap real, correctly-
    matched speech once everything is sorted into true audio order.
    """
    if not edited_tokens:
        return []

    encoder = phonetic_encoder if phonetic_encoder is not None else _DEFAULT_PHONETIC_ENCODER
    stt_norm = normalize_for_alignment([w.text for w in stt_words], phonetic_encoder=encoder)
    edited_norm = normalize_for_alignment([t.text for t in edited_tokens], phonetic_encoder=encoder)
    backbone, displaced_blocks = find_displaced_blocks(stt_norm, edited_norm)

    # Merge backbone + every displaced block into one edited-order chain,
    # each entry tagged with which chain it belongs to.
    tagged: list[tuple[int, int, str | int]] = [(s, e, _BACKBONE_GROUP) for s, e in backbone]
    for block_id, block in enumerate(displaced_blocks):
        tagged.extend((s, e, block_id) for s, e in block)
    tagged.sort(key=lambda t: t[1])

    aligned: list[AlignedWord] = []

    edges: list[tuple[int, int, str | int]] = [
        (-1, -1, _START_GROUP),
        *tagged,
        (len(stt_words), len(edited_tokens), _END_GROUP),
    ]
    for (prev_stt, prev_edited, prev_group), (next_stt, next_edited, next_group) in pairwise(edges):
        if _group_compatible(prev_group, next_group):
            aligned.extend(
                _dp_segment(stt_norm, edited_norm, stt_words, edited_tokens, prev_stt, prev_edited, next_stt, next_edited)
            )
        else:
            # Crossing a chain boundary: the (prev.stt+1, next.stt) range
            # isn't trustworthy here (see `_group_compatible`), so every
            # edited token in this range is left unmatched — genuinely
            # orphaned, belonging to no chain at all. Resolved with AT MOST
            # ONE real anchor as a bound (prev_stt's, preferred, else
            # next_stt's) — NEVER both together, since the two chains are
            # non-audio-adjacent by definition here, and bounding against
            # both would be exactly the "bridge across a chain boundary"
            # bug relocated to this second site. One-sided bounding
            # degrades to a zero-duration placement pinned at whichever
            # anchor IS trusted (interpolate_gaps' existing "no neighbor on
            # this side" behavior) — safe (never overlaps real content) and
            # honest (confidence 0.0 either way).
            orphan_words = [
                AlignedWord(
                    token=edited_tokens[prev_edited + 1 + local_edited],
                    start=0.0,
                    end=0.0,
                    match_type=MatchType.INTERPOLATED,
                    confidence=0.0,
                )
                for local_edited in range(next_edited - prev_edited - 1)
            ]
            if orphan_words:
                dummy_token = edited_tokens[0]
                if 0 <= prev_stt < len(stt_words):
                    fence = [_boundary_word(stt_words[prev_stt], dummy_token)]
                    resolved_orphans = interpolate_gaps(fence + orphan_words)[len(fence) :]
                elif 0 <= next_stt < len(stt_words):
                    fence = [_boundary_word(stt_words[next_stt], dummy_token)]
                    resolved_orphans = interpolate_gaps(orphan_words + fence)[: -len(fence)]
                else:
                    resolved_orphans = orphan_words  # no real anchor on either side at all
                aligned.extend(resolved_orphans)

        if next_group != _END_GROUP:  # a real anchor, not the trailing sentinel
            token = edited_tokens[next_edited]
            anchor_word = stt_words[next_stt]
            aligned.append(
                AlignedWord(
                    token=token,
                    start=anchor_word.start,
                    end=anchor_word.end,
                    match_type=MatchType.ANCHOR,
                    confidence=_CONFIDENCE_BY_MATCH_TYPE[MatchType.ANCHOR],
                    speaker=anchor_word.speaker,
                )
            )

    aligned.sort(key=lambda w: w.token.index)

    # NOT a final global interpolate_gaps() pass: every INTERPOLATED entry
    # above was already resolved locally — by `_dp_segment` (bounded by its
    # own segment's real anchors) or by the orphan-run fencing (bounded by
    # at most one real anchor, never two from different chains).
    # interpolate_gaps decides what to fill purely by
    # `match_type == INTERPOLATED`, with no way to tell "already resolved,
    # bounded correctly" from "still a raw placeholder" — a second global
    # call would silently RE-interpolate every entry using whatever flanks
    # it in the fully-merged, cross-chain list, undoing both fixes at once.
    logger.debug(
        "aligned %d edited tokens: %d anchors, %d displaced blocks, %d interpolated",
        len(aligned),
        len(backbone),
        len(displaced_blocks),
        sum(1 for w in aligned if w.match_type == MatchType.INTERPOLATED),
    )
    return aligned


def resolve_audio_order(words: list[AlignedWord]) -> tuple[list[AlignedWord], list[QCIssue]]:
    """The S3/S5 boundary contract: sort `align()`'s edited-order output
    into AUDIO order (by true timestamp), and flag every displaced block
    found along the way. Every consumer downstream of S3 (cue segmentation,
    export) MUST receive this function's output, never `align()`'s raw
    return value — see `segment.cue_segmenter.segment_into_cues`'s own
    precondition assertion, which enforces this at its boundary too.

    Why sorting, not tolerating out-of-order input downstream: a displaced
    block's content was spoken at one point in the audio and placed at a
    different point in the document. Captions emitted in document order but
    carrying true (audio) timing would show the moved text while the viewer
    hears audio from elsewhere. There is no valid VTT that satisfies both
    orderings: captions are a timeline format, and the timeline belongs to
    the audio. So the export path receives words in audio order, always.
    `token.index` still records the original document position on every
    word, so document order is always reconstructable for a round-trip
    check — nothing is lost here, only reordered, and the reordering is
    reported, not silently applied.

    Detection: after sorting by `(start, token.index)`, a token whose
    edited-stream index is LOWER than the highest index already seen in
    audio order is out of document order. Maximal contiguous (in audio
    order) runs of such tokens each produce one
    `QCIssue(code=TRANSPOSED_BLOCK, severity="info")` naming the
    edited-index span that moved — a "a human should decide whether the
    caption follows the audio or the document" flag, not a defect being
    silently corrected.
    """
    audio_order = sorted(words, key=lambda w: (w.start, w.token.index))

    issues: list[QCIssue] = []
    running_max_index = -1
    run_indices: list[int] = []

    def _flush_run() -> None:
        if not run_indices:
            return
        issues.append(
            QCIssue(
                severity="info",
                code=QCCode.TRANSPOSED_BLOCK,
                message=(
                    f"tokens at edited indices {min(run_indices)}-{max(run_indices)} appear out of "
                    "document order in the audio timeline — the editor moved this content; captions "
                    "follow the audio, not the document"
                ),
                cue_index=None,
            )
        )

    for w in audio_order:
        idx = w.token.index
        if idx < running_max_index:
            run_indices.append(idx)
        else:
            _flush_run()
            run_indices = []
        running_max_index = max(running_max_index, idx)
    _flush_run()

    return audio_order, issues
