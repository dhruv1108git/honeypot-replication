"""Autorater run as four stages: load -> rate -> score -> write.

Each stage is a plain function so it can be run and inspected on its own; the
CLI just chains them.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from . import metrics
from .autorater import Autorater, VerdictParseError
from .client import GatewayError
from .data import Example, load_dataset, load_registry
from .policy import Thresholds


@dataclass
class RatedItem:
    example: Example
    score: float | None = None
    pred_category: str = "none"
    rationale: str = ""
    reply: str = ""
    error: str | None = None
    pred: bool | None = None      # set by score(), from the threshold

    def to_json(self) -> dict:
        d = asdict(self.example)
        d.update({"score": self.score, "pred": self.pred, "pred_category": self.pred_category,
                  "rationale": self.rationale, "reply": self.reply, "error": self.error})
        return d


def load(cfg: dict, dataset: str | None = None, limit: int | None = None) -> list[Example]:
    registry = load_registry(cfg["data"]["registry"])
    return load_dataset(registry, dataset or cfg["data"]["dataset"], limit=limit)


def _rate_one(rater: Autorater, ex: Example) -> RatedItem:
    try:
        r = rater.rate(ex)
        return RatedItem(ex, score=r.score, pred_category=r.category, rationale=r.rationale, reply=r.reply)
    except (GatewayError, VerdictParseError) as e:
        return RatedItem(ex, error=f"{type(e).__name__}: {e}")


def rate(rater: Autorater, examples: list[Example], workers: int = 1) -> list[RatedItem]:
    """Rate every example; results come back in input order whatever the worker count."""
    if workers <= 1:
        return [_rate_one(rater, ex) for ex in examples]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda ex: _rate_one(rater, ex), examples))


def score(rated: list[RatedItem], thresholds: Thresholds) -> dict:
    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
    ok = [r for r in rated if r.error is None]
    for r in ok:
        r.pred = thresholds.is_violation(r.score, r.pred_category)
    summary = metrics.summarize([r.example.is_violation for r in ok], [bool(r.pred) for r in ok])
    summary["errors"] = len(rated) - len(ok)
    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
    return summary


def write(out_root: str | Path, rated: list[RatedItem], summary: dict) -> Path:
    out_dir = Path(out_root) / time.strftime("%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in rated:
            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return out_dir
