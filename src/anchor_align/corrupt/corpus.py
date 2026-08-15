"""S1 — synthetic gold corpus generator.

The single hand-written fixture has only 2-5 occurrences of several
transform opportunities, which admits only a handful of achievable
fractions — no statistical power to see `level` produce a gradient, and no
pause structure for a time-weighted metric to measure.

This module does NOT fix calibration: base rates are still tuned by feel,
not against real (raw transcript, published edited transcript) pairs. What
it fixes is statistical power — more opportunities per transform, spread
across more documents — and real pause structure: words get jittered
per-word durations around a plausible speaking rate, and sentence
boundaries get an occasional pause, so a boundary-error metric can
distinguish "one token slipped inside fast speech" from "one token slipped
across a two-second pause".
"""

from __future__ import annotations

import random
import re

from anchor_align.models import STTWord

# One string per paragraph, deliberately varied in *character*, not just
# wording, so opportunity density varies by document depending on which
# templates a given doc draws: some are filler-heavy, some name/acronym-
# heavy, some numeral-heavy, some nearly clean.
TEMPLATES: tuple[str, ...] = (
    "So the project started last spring and honestly it was um a mess at first.",
    "We we spent three weeks just trying to get the the pipeline working end to end.",
    "I don't think anyone on the team expected it to take that long, actually.",
    "The the F B I released a report about it, which uh surprised everyone in the room.",
    "Siobhan was the one who finally found the bug in the ingestion layer.",
    "About twenty percent of the requests were failing silently before that fix landed.",
    "Later we brought in Siobhan again to review the thirty five remaining edge cases.",
    "It won't be easy to hit the deadline but the team is optimistic about it.",
    "Honestly the whole thing was uh basically a lesson in patience for everyone involved.",
    "We shipped the first version on a Friday afternoon, which in hindsight was risky.",
    "The C I A style compartmentalization of the codebase actually helped a lot here.",
    "Nobody expected the migration to go this smoothly given how old the system was.",
    "It's still not perfect but the numbers keep improving every single week now.",
    "Can't say we solved everything but the worst failure modes are gone for good.",
    "Yosemite was the code name for the original prototype, before anyone renamed it.",
    "We we we kept hitting the the same wall over and over, uh, for two full months.",
    "Roughly fifty percent of users churned in the first thirty days after launch.",
    "The N A S A style review process caught fourteen bugs before the freeze.",
    "Won't lie, the on call rotation that quarter was basically a nightmare for everyone.",
    "About ninety percent of the alerts turned out to be false positives, uh, in the end.",
    "Yosemite's successor shipped quietly, actually, with almost no fanfare at all.",
    "Siobhan and the the rest of the team basically rebuilt it from scratch that winter.",
    "It's not that complicated once you actually sit down and read the the spec closely.",
    "Twenty five percent faster isn't nothing, but uh it's not the win we were hoping for.",
    "The U S B driver update fixed about sixty percent of the reported crashes overnight.",
    "Can't remember exactly when it broke, honestly, but it was definitely before the freeze.",
    "We shipped fixes for the top ten issues, then, uh, immediately found twenty more.",
    "Don't ask me why it took so long, actually — the the root cause was almost trivial.",
    "Siobhan's fix for the F B I compliance report took barely twenty minutes, in the end.",
    "About eighty five percent of the test suite runs green now, up from basically nothing.",
)

_SENTENCE_END = re.compile(r"[.!?]$")


def _sentence_boundaries(tokens: list[str]) -> set[int]:
    """Indices i such that tokens[i] ends a sentence (a pause may follow)."""
    return {i for i, t in enumerate(tokens) if _SENTENCE_END.search(t)}


def _synthesize_words(tokens: list[str], rng: random.Random) -> list[STTWord]:
    """Assign timing: ~2.5 words/sec base rate with per-word jitter, plus
    an occasional longer pause after a sentence boundary."""
    boundaries = _sentence_boundaries(tokens)
    words: list[STTWord] = []
    t = 0.0
    for i, text in enumerate(tokens):
        duration = max(0.08, rng.gauss(0.4, 0.12))
        start = t
        end = start + duration
        words.append(STTWord(text=text, start=start, end=end))
        gap = rng.uniform(0.02, 0.08)
        if i in boundaries and rng.random() < 0.6:
            gap += rng.uniform(0.3, 1.2)  # a real pause: breath, thought, topic shift
        t = end + gap
    return words


def generate_corpus(
    n_docs: int, *, seed: int, min_paragraphs: int = 2, max_paragraphs: int = 5
) -> list[tuple[str, list[STTWord]]]:
    """Return `n_docs` synthetic (doc_id, gold_words) pairs, deterministic
    given `seed`. Each document samples a random number of paragraphs (with
    replacement) from TEMPLATES, then gets independently jittered timing."""
    corpus: list[tuple[str, list[STTWord]]] = []
    for doc_index in range(n_docs):
        doc_id = f"synthetic-{seed}-{doc_index:03d}"
        doc_rng = random.Random(f"{seed}:{doc_index}")
        n_paragraphs = doc_rng.randint(min_paragraphs, max_paragraphs)
        paragraphs = [doc_rng.choice(TEMPLATES) for _ in range(n_paragraphs)]
        tokens = [tok for para in paragraphs for tok in para.split()]
        words = _synthesize_words(tokens, doc_rng)
        corpus.append((doc_id, words))
    return corpus


def generate_long_document(
    *, seed: int, target_word_count: int = 8000, doc_id: str | None = None
) -> tuple[str, list[STTWord]]:
    """One long synthetic document — 8000 words is roughly 65 minutes at
    this module's ~2.5 words/sec pacing, well past the "does it still line
    up after 40 minutes" question a drift metric exists to answer.

    A unique "checkpointNNNN" marker word is inserted before each sampled
    paragraph. Without it, `find_anchors` requires a word to appear EXACTLY
    ONCE in each stream — with only 30 templates repeated over a document
    this long, every otherwise-anchor-worthy word recurs and none would
    qualify, leaving one enormous unanchored segment (computationally
    pathological for S3b's O(n*m) DP, and not a fair test of anchoring).
    Real long-form speech has this property too: proper nouns and numbers
    recur throughout a long talk, not just once at the very start.
    """
    rng = random.Random(f"long:{seed}")
    tokens: list[str] = []
    checkpoint = 0
    while len(tokens) < target_word_count:
        tokens.append(f"checkpoint{checkpoint}")
        tokens.extend(rng.choice(TEMPLATES).split())
        checkpoint += 1
    words = _synthesize_words(tokens, rng)
    return (doc_id or f"synthetic-long-{seed}", words)
