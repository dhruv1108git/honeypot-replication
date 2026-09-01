"""Which reasoning text goes into the training target.

Since the 08-04 export the conversation records carry the model's raw
reasoning (`reasoning`) next to the short summary (`reasoning_summary`).
The data config picks one with `thought_source`:

    raw      raw reasoning, falling back to the summary for older records
    summary  the summary only (the behaviour before this option existed)
    none     no reasoning in the target

The chosen text is cleaned up but not rewritten: we only strip surrounding
whitespace, normalise line endings and drop the export job's chunk markers.
"""
from __future__ import annotations

import re
from collections import Counter
from enum import Enum

# The export job splits long reasoning into chunks joined with this marker.
_CHUNK_MARKER = re.compile(r"\n?<\|reasoning_chunk\|>\n?")


class ThoughtSource(str, Enum):
    RAW = "raw"
    SUMMARY = "summary"
    NONE = "none"

    @classmethod
    def parse(cls, value: str) -> "ThoughtSource":
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"thought_source must be one of {[s.value for s in cls]}, got {value!r}") from None


def clean_reasoning(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = _CHUNK_MARKER.sub("\n", text)
    return text.strip()


def select_thought(rec: dict, source: ThoughtSource = ThoughtSource.RAW,
                   stats: Counter | None = None) -> str | None:
    """Return the reasoning text for `rec`, or None. Counts the origin in `stats`."""
    origin, text = "none", None
    if source is ThoughtSource.RAW and rec.get("reasoning"):
        origin, text = "raw", clean_reasoning(rec["reasoning"])
    if not text and source in (ThoughtSource.RAW, ThoughtSource.SUMMARY) and rec.get("reasoning_summary"):
        origin, text = "summary", rec["reasoning_summary"].strip()
    if not text:
        origin, text = "none", None
    if stats is not None:
        stats[origin] += 1
    return text
