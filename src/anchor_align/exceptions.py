"""Exceptions raised by anchor_align itself.

Pipeline failures that carry context (which file, which stage) inherit
:class:`RuntimeError` so callers written against the original
bare-``RuntimeError`` raises keep working; :class:`AnchorAlignError` is the
umbrella for anyone who wants to catch only our errors. Input-contract
violations (unsorted input, mismatched lengths) deliberately stay plain
``ValueError`` — those are programming errors, not pipeline failures.
"""


class AnchorAlignError(Exception):
    """Base class for every error raised by anchor_align code."""


class IngestError(AnchorAlignError, RuntimeError):
    """Audio or transcript ingestion failed."""


class TranscriptionError(AnchorAlignError, RuntimeError):
    """An STT adapter could not produce a transcription."""
