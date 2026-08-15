"""S4 — benchmarking-only adapters between S1's synthetic output and the
real pipeline shapes.

Kept in production code (not tests) so the four benchmark test files and
`benchmark.runner` share one implementation instead of five copies.
This is NOT the real S1<->S2 char-span bridge: `char_offset` here is a
cumulative character count over the corrupted token stream itself, which
has no source document to offset into. Good enough to satisfy
`EditedToken`'s shape for the aligners; not a stand-in for S2's adapter.
"""

from __future__ import annotations

import re

from anchor_align.models import EditedToken

_SENTENCE_END = re.compile(r"[.!?]$")


def to_edited_tokens(tokens: tuple[str, ...]) -> list[EditedToken]:
    result = []
    sentence_id = 0
    char_offset = 0
    for i, text in enumerate(tokens):
        is_end = bool(_SENTENCE_END.search(text))
        result.append(
            EditedToken(text=text, index=i, char_offset=char_offset, sentence_id=sentence_id, is_sentence_end=is_end)
        )
        char_offset += len(text) + 1
        if is_end:
            sentence_id += 1
    return result
