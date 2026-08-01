"""Which reasoning text goes into the training target.

The export job attaches a short reasoning summary to each response. We train
the model to produce the summary before its answer.
"""
from __future__ import annotations


def select_thought(rec: dict) -> str | None:
    summary = rec.get("reasoning_summary")
    if not summary:
        return None
    summary = summary.strip()
    return summary or None
