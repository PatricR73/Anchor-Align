"""S1 <-> S2 mapping-representation bridge — recorded as a stub so the
requirement doesn't evaporate before S2 exists.

`TokenMapping` (S1, corrupt/corruptor.py) is index-based: the corruptor
generates the edited stream itself, so its indices are authoritative and
free. S2 has no such guarantee — it ingests a real human-edited .docx where
the only reliable anchor is `EditedToken.char_offset`, a character offset
into the source document. See the design note on `TokenMapping` in
models.py for why the two representations are kept separate rather than
unified into one span-based scheme.

Once an adapter between the two exists (`TokenMapping` indices <->
`EditedToken` char spans), this test must assert that converting S1's
synthetic output through the adapter and back is lossless: for every
`CorruptionConfig`-driven relation (IDENTITY, SUBSTITUTE, SPLIT, MERGE,
INSERTED), the round-tripped mapping must equal the original. Until then it
stays an explicit failure rather than a silently-missing test.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(
    strict=True,
    reason="the TokenMapping <-> EditedToken char-span adapter does not exist yet; "
    "implement it, then replace this stub with the real round-trip assertion",
)
def test_index_mapping_to_char_span_and_back_round_trips_on_synthetic_s1_output():
    raise NotImplementedError
