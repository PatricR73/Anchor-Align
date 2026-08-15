"""Contraction table shared by S1 (corruptor simulates expansion) and S2
(normalizer adds expansion variants). Single source so the two stages
cannot drift apart.
"""

CONTRACTIONS: dict[str, tuple[str, str]] = {
    "don't": ("do", "not"),
    "can't": ("can", "not"),
    "it's": ("it", "is"),
    "won't": ("will", "not"),
}
