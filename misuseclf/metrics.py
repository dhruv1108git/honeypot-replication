"""Classification metrics for autorater runs. Positive class = "violation"."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class Confusion:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @classmethod
    def from_preds(cls, labels: Sequence[bool], preds: Sequence[bool]) -> "Confusion":
        if len(labels) != len(preds):
            raise ValueError("labels and preds differ in length")
        tp = sum(1 for y, p in zip(labels, preds) if y and p)
        fp = sum(1 for y, p in zip(labels, preds) if not y and p)
        fn = sum(1 for y, p in zip(labels, preds) if y and not p)
        return cls(tp=tp, fp=fp, tn=len(labels) - tp - fp - fn, fn=fn)

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def precision(self) -> float:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def fpr(self) -> float:
        return _ratio(self.fp, self.fp + self.tn)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict:
        return {**asdict(self), "n": self.n, "precision": self.precision, "recall": self.recall,
                "fpr": self.fpr, "f1": self.f1}


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> dict[str, int]:
    """Kept for callers of the old dict API."""
    c = Confusion.from_preds(labels, preds)
    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}


def summarize(labels: Sequence[bool], preds: Sequence[bool]) -> dict:
    return Confusion.from_preds(labels, preds).as_dict()
