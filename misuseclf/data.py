"""Labelled examples for autorater runs, the dataset registry and row validation."""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .policy import CATEGORIES, LABELS

REQUIRED_FIELDS = ("id", "request", "label", "category")


class SchemaError(ValueError):
    """A row of a labelled set does not match the expected schema."""


@dataclass(frozen=True)
class Example:
    id: str
    request: str        # the user request as received
    label: str          # "violation" or "benign"
    category: str       # taxonomy key, or "none" for benign items

    @property
    def is_violation(self) -> bool:
        return self.label == "violation"


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    path: Path
    version: str
    description: str = ""


def load_registry(path: str | Path) -> dict[str, DatasetSpec]:
    with open(path, "rb") as f:
        raw = tomllib.load(f).get("datasets", {})
    root = Path(path).resolve().parent.parent
    return {
        name: DatasetSpec(name=name, path=root / d["path"], version=str(d.get("version", "unknown")),
                          description=d.get("description", ""))
        for name, d in raw.items()
    }


def validate_row(d: dict, where: str) -> Example:
    missing = [k for k in REQUIRED_FIELDS if k not in d]
    if missing:
        raise SchemaError(f"{where}: missing fields {missing}")
    for k in REQUIRED_FIELDS:
        if not isinstance(d[k], str):
            raise SchemaError(f"{where}: field {k!r} must be a string, got {type(d[k]).__name__}")
    if d["label"] not in LABELS:
        raise SchemaError(f"{where}: label {d['label']!r} not in {LABELS}")
    if d["label"] == "violation" and d["category"] not in CATEGORIES:
        raise SchemaError(f"{where}: violation with unknown category {d['category']!r}")
    if d["label"] == "benign" and d["category"] != "none":
        raise SchemaError(f"{where}: benign item must have category 'none', got {d['category']!r}")
    return Example(d["id"], d["request"], d["label"], d["category"])


def load_jsonl(path: str | Path, limit: int | None = None) -> list[Example]:
    out: list[Example] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            where = f"{path}:{lineno}"
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                raise SchemaError(f"{where}: invalid JSON ({e})") from None
            ex = validate_row(d, where)
            if ex.id in seen:
                raise SchemaError(f"{where}: duplicate id {ex.id!r}")
            seen.add(ex.id)
            out.append(ex)
            if limit is not None and len(out) >= limit:
                break
    return out


def load_dataset(registry: dict[str, DatasetSpec], name: str, limit: int | None = None) -> list[Example]:
    try:
        spec = registry[name]
    except KeyError:
        raise KeyError(f"unknown dataset {name!r}; registered: {sorted(registry)}") from None
    return load_jsonl(spec.path, limit=limit)
