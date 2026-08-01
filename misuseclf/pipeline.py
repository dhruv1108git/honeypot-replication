"""Autorater run as four stages: load -> rate -> score -> write.

Each stage is a plain function so it can be run and inspected on its own; the
CLI just chains them.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import metrics
from .autorater import Autorater, VerdictParseError
from .client import GatewayError
from .data import Example, load_dataset, load_registry


@dataclass
class RatedItem:
    example: Example
    pred: bool | None = None
    pred_category: str = "none"
    reply: str = ""
    error: str | None = None

    def to_json(self) -> dict:
        d = asdict(self.example)
        d.update({"pred": self.pred, "pred_category": self.pred_category, "reply": self.reply,
                  "error": self.error})
        return d


def load(cfg: dict, dataset: str | None = None, limit: int | None = None) -> list[Example]:
    registry = load_registry(cfg["data"]["registry"])
    return load_dataset(registry, dataset or cfg["data"]["dataset"], limit=limit)


def rate(rater: Autorater, examples: list[Example]) -> list[RatedItem]:
    out = []
    for ex in examples:
        try:
            r = rater.rate(ex)
            out.append(RatedItem(ex, pred=r.violation, pred_category=r.category, reply=r.reply))
        except (GatewayError, VerdictParseError) as e:
            out.append(RatedItem(ex, error=f"{type(e).__name__}: {e}"))
    return out


def score(rated: list[RatedItem]) -> dict:
    ok = [r for r in rated if r.error is None]
    summary = metrics.summarize([r.example.is_violation for r in ok], [bool(r.pred) for r in ok])
    summary["errors"] = len(rated) - len(ok)
    return summary


def write(out_root: str | Path, rated: list[RatedItem], summary: dict) -> Path:
    out_dir = Path(out_root) / time.strftime("%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in rated:
            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return out_dir
