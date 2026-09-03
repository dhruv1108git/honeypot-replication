"""Record types and JSONL helpers.

Raw records come from the conversation export job, one JSON object per line:

    {"id": "...", "messages": [{"role": "user", "content": "..."}],
     "response": "...", "reasoning_summary": "...",
     "grader": {"quality": 0.82, "flags": []}}
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


@dataclass
class Example:
    id: str
    source: str
    messages: list[dict]
    response: str
    thought: str | None = None
    thought_truncated: bool = False
    quality: float = 0.0
    flags: list[str] = field(default_factory=list)
    prompt_text: str = ""
    target_text: str = ""
    n_tokens: int = 0

    def to_json(self) -> dict:
        return asdict(self)


def iter_jsonl(path: str | Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: bad JSON: {e}") from e


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    n = 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def example_from_record(rec: dict, source: str) -> Example:
    grader = rec.get("grader") or {}
    return Example(
        id=str(rec["id"]),
        source=source,
        messages=list(rec.get("messages") or []),
        response=rec.get("response") or "",
        quality=float(grader.get("quality", 0.0)),
        flags=list(grader.get("flags") or []),
    )
