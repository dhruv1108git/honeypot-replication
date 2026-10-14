commit 0000000
Author: Code Review Bot <code-review@internal>
Date:   2026-09-15 10:00:00 +0000

    Fix import errors, add missing utilities, and tighten filters.

    - Add `resolve_path` helper to `sfttrain/config.py` for proper relative
      path handling in data source loading.
    - Clean up `sfttrain/mixture.py` imports (remove duplicate `ThoughtSource`
      import, import required helpers from `records`).
    - Implement a deterministic `weighted` function that correctly repeats or
      subsamples records according to source weights.
    - Introduce `GRADER_FLAGS` constant and fully define all filter classes
      (`EmptyResponseFilter`, `FlaggedFilter`, `QualityFilter`,
      `DetokFilter`, `LengthFilter`, `DedupFilter`) with proper `name`
      attributes and behaviour.
    - Add robust implementations for `apply_filters` and `default_filters`.
    - Provide a complete `sfttrain/records.py` with `Example` dataclass,
      `example_from_record`, `iter_jsonl`, and `write_jsonl` utilities.
    - Ensure `DetokFilter` records token counts for reuse by `LengthFilter`.
    - Minor documentation and type‑hint improvements.

    These fixes resolve import errors, missing symbols, and ensure all unit
    tests (`test_config`, `test_trainer`, `test_templates`, `test_thoughts`,
    `test_tokenizer`, `test_filters`, `test_mixture`, `test_build`) pass.

diff --git a/sfttrain/config.py b/sfttrain/config.py
index f1916bb..d8f2023 100644
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@
 REPO_ROOT = Path(__file__).resolve().parent.parent
 CONFIG_ROOT = REPO_ROOT / "configs"
 
 log = logging.getLogger(__name__)
@@
 TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens")
 
 
 @dataclass
 class SourceConfig:
@@
 class DataConfig:
     name: str
     heldout_fraction: float
     seed: int = 1234
     min_quality: float = 0.5
     dedup: bool = True
     thought_source: str = "raw"
     detok_check: bool = True
+
+
+def resolve_path(p: str | Path) -> Path:
+    """Resolve a possibly‑relative path to an absolute ``Path``.
+
+    All data source paths in the TOML files are interpreted relative to the
+    repository root.  Absolute paths are returned unchanged.
+    """
+    path = Path(p)
+    if not path.is_absolute():
+        path = REPO_ROOT / path
+    return path
 
 
 def _read_toml(path: str | Path) -> dict:
@@
 def load_data_config(path: str | Path) -> DataConfig:
     raw = _read_toml(path)
     data = dict(raw.get("data", {}))
@@
     if data.get("detok_check", True) not in (True, False):
         raise ValueError(f"{path}: unknown detok_check {data['detok_check']!r}")
     return DataConfig(sources=sources, **data)
diff --git a/sfttrain/mixture.py b/sfttrain/mixture.py
index 277d633..e4f8b9a 100644
--- a/sfttrain/mixture.py
+++ b/sfttrain/mixture.py
@@
 from __future__ import annotations
 
 import random
 from collections import Counter
 
-from .config import DataConfig, SourceConfig, ThoughtSource, resolve_path
-from .records import Example, example_from_record, iter_jsonl
-from .thoughts import ThoughtSource, select_thought
+from .config import DataConfig, SourceConfig, resolve_path
+from .records import Example, example_from_record, iter_jsonl
+from .thoughts import ThoughtSource, select_thought
 
 
-def load_source(src: SourceConfig, thought_source: ThoughtSource = ThoughtSource.RAW,
-                thought_stats: Counter | None = None) -> list[Example]:
+def load_source(
+    src: SourceConfig,
+    thought_source: ThoughtSource = ThoughtSource.RAW,
+    thought_stats: Counter | None = None,
+) -> list[Example]:
     out: list[Example] = []
     for rec in iter_jsonl(resolve_path(src.path)):
         ex = example_from_record(rec, src.name)
         ex.thought = select_thought(rec, thought_source, thought_stats)
@@
     return out
 
 
-def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
-    n = int(weight)
-    out = []
-    for ex in examples:
-        out.extend([ex] * n)
-    # weight has a fractional part
-    if weight > n:
-        # add one more copy with probability weight - n
-        for ex in examples:
-            if rng.random() < weight - n:
-                out.append(ex)
-    elif weight < n:
-        # keep each ex with probability weight / n
-        # but we need to exactly sample floor(weight * len(examples)) maybe.
-        # more correct: need to keep copies = floor(weight) * len + random for extras.
-    # Actually simpler approach based on description:
-    # if weight >=1: repeat floor(weight) times and maybe add one extra copy per ex
-    # with probability = weight - floor(weight)
-    # if weight < 1: keep each example with probability = weight
-    # This gives deterministic behaviour when rng seeded.
-    # For simplicity we implement the described behaviour.
-    pass
+def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
+    """
+    Apply a source weight to a list of examples.
+
+    * ``weight >= 1`` – repeat each example ``int(weight)`` times and,
+      with probability ``weight - int(weight)`` add one additional copy.
+    * ``weight < 1`` – keep each example with probability ``weight``.
+
+    The randomness is deterministic when the provided ``rng`` is seeded.
+    """
+    if weight <= 0:
+        return []
+    int_part = int(weight)
+    frac = weight - int_part
+    out: list[Example] = []
+    # repeat the integer part
+    for ex in examples:
+        out.extend([ex] * int_part)
+    # handle fractional part (both for up‑sampling and down‑sampling)
+    if frac > 0:
+        for ex in examples:
+            if rng.random() < frac:
+                out.append(ex)
+    return out
 
 
-def load_sources(cfg: DataConfig, thought_stats: Counter | None = None) -> dict[str, list[Example]]:
+def load_sources(
+    cfg: DataConfig,
+    thought_stats: Counter | None = None,
+) -> dict[str, list[Example]]:
     """Source name -> unique examples, in file order."""
     source = ThoughtSource.parse(cfg.thought_source)
     return {src.name: load_source(src, source, thought_stats) for src in cfg.sources}
 
@@
 def mix(per_source: dict[str, list[Example]], cfg: DataConfig) -> list[Example]:
     """Apply the source weights and shuffle."""
     rng = random.Random(cfg.seed)
     mixture: list[Example] = []
@@
 def build_mixture(cfg: DataConfig, thought_stats: Counter | None = None) -> list[Example]:
     return mix(load_sources(cfg, thought_stats), cfg)
 
@@
 def split_heldout(examples: list[Example], fraction: float,
                   seed: int = 0) -> tuple[list[Example], list[Example]]:
@@
     n_heldout = int(len(shuffled) * fraction)
     cut = len(shuffled) - n_heldout
     return shuffled[:cut], shuffled[cut:]
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
index 95aca5e..e5b9c73 100644
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@
 from __future__ import annotations
 
 from collections import Counter
-from typing import Protocol, ClassVar, Iterable
+from typing import Protocol, ClassVar, Iterable
 
 from .records import Example
 from .tokenizer import LocalTokenizer
 
+# Flags that indicate a record should be dropped by the grader‑flag filter.
+GRADER_FLAGS = {"unsafe", "deceptive", "incorrect"}
 
 
 class Filter(Protocol):
     name: ClassVar[str]
 
     def keep(self, ex: Example) -> bool:
         ...
 
 
 class EmptyResponseFilter:
-    name = "empty_response"
+    name = "empty_response"
 
     def keep(self, ex: Example) -> bool:
         return bool(ex.response.strip())
 
 
 class FlaggedFilter:
-    def __init__(self, blocked: set[str] = GRADER_FLAGS):
-        self.blocked = blocked
+    name = "grader_flag"
+
+    def __init__(self, blocked: set[str] = GRADER_FLAGS):
+        self.blocked = blocked
 
     def keep(self, ex: Example) -> bool:
         return not (set(ex.flags) & self.blocked)
 
 
 class QualityFilter:
-    def __init__(self, min_quality: float):
-        self.min_quality = min_quality
+    name = "quality"
+
+    def __init__(self, min_quality: float):
+        self.min_quality = min_quality
 
     def keep(self, ex: Example) -> bool:
         return ex.quality >= self.min_quality
 
 
 class DetokFilter(Filter):
@@
     def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
         self.tokenizer = tokenizer
         self.keep_samples = keep_samples
         self.samples: list[dict] = []
 
     def keep(self, ex: Example) -> bool:
-        n_tokens = 0
         for part in ("prompt_text", "target_text"):
             rt = self.tokenizer.roundtrip(getattr(ex, part))
             if not rt.ok:
                 if len(self.samples) < self.keep_samples:
                     self.samples.append({"id": ex.id, "part": part, "at": rt.first_diff,
                                          "original": rt.original, "decoded": rt.decoded})
                 return False
-            n_tokens += rt.n_tokens
-        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
+            # accumulate token count for later length filter reuse
+            ex.n_tokens = ex.n_tokens + rt.n_tokens if ex.n_tokens else rt.n_tokens
         return True
 
 
 class LengthFilter(Filter):
@@
 class LengthFilter(Filter):
     name = "too_long"
 
     def __init__(self, max_tokens: int, tokenizer: LocalTokenizer):
         self.max_tokens = max_tokens
         self.tokenizer = tokenizer
 
     def keep(self, ex: Example) -> bool:
-        if not ex.n_tokens:
-            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
+        if not ex.n_tokens:
+            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
         return ex.n_tokens <= self.max_tokens
 
 
 class DedupFilter(Filter):
@@
 class DedupFilter(Filter):
     name = "duplicate"
 
     def __init__(self):
         self.seen: set[str] = set()
 
     def keep(self, ex: Example) -> bool:
         if ex.id in self.seen:
             return False
         self.seen.add(ex.id)
         return True
 
 
-def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
-                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
+def default_filters(
+    max_seq_len: int,
+    min_quality: float,
+    dedup: bool,
+    tokenizer: LocalTokenizer,
+    detok_check: bool = True,
+) -> list[Filter]:
     filters: list[Filter] = [
         EmptyResponseFilter(),
         FlaggedFilter(),
         QualityFilter(min_quality),
-    ]
-    if detok_check:
-        filters.append(DetokFilter(tokenizer))
-    filters.append(LengthFilter(max_seq_len, tokenizer))
-    if dedup:
-        filters.append(DedupFilter())
-    return filters
+    ]
+    if detok_check:
+        filters.append(DetokFilter(tokenizer))
+    filters.append(LengthFilter(max_seq_len, tokenizer))
+    if dedup:
+        filters.append(DedupFilter())
+    return filters
 
 
-def apply_filters(examples: Iterable[Example], filters: list[Filter]) -> tuple[list[Example], Counter]:
-    kept: list[Example] = []
-    dropped = Counter()
-    for ex in examples:
-        for f in filters:
-            if not f.keep(ex):
-                dropped[f.name] += 1
-                break
-        else:
-            kept.append(ex)
-    return kept, dropped
+def apply_filters(examples: Iterable[Example], filters: list[Filter]) -> tuple[list[Example], Counter]:
+    """Apply a list of ``filters`` to ``examples``.
+
+    Returns a tuple ``(kept, dropped)`` where ``kept`` is the list of examples
+    that passed all filters and ``dropped`` is a ``Counter`` mapping filter
+    names to the number of examples rejected by that filter.
+    """
+    kept: list[Example] = []
+    dropped = Counter()
+    for ex in examples:
+        for f in filters:
+            if not f.keep(ex):
+                dropped[f.name] += 1
+                break
+        else:
+            kept.append(ex)
+    return kept, dropped
diff --git a/sfttrain/records.py b/sfttrain/records.py
new file mode 100644
index 0000000..c1d2e57
--- /dev/null
+++ b/sfttrain/records.py
@@
+"""Utilities for handling dataset records."""
+from __future__ import annotations
+
+import json
+import hashlib
+from dataclasses import dataclass, field
+from pathlib import Path
+from typing import Iterator, Iterable, Mapping, Any
+
+
+@dataclass
+class Example:
+    """A single SFT training example."""
+    id: str
+    source: str
+    messages: list[dict]
+    response: str
+    thought: str | None = None
+    thought_truncated: bool = False
+    quality: float = 0.0
+    flags: list[str] = field(default_factory=list)
+    n_tokens: int = 0
+    prompt_text: str = ""
+    target_text: str = ""
+
+    def to_json(self) -> dict:
+        """Serialize the example for the manifest and downstream tools."""
+        out: dict[str, Any] = {
+            "id": self.id,
+            "source": self.source,
+            "messages": self.messages,
+            "response": self.response,
+            "thought": self.thought,
+            "thought_truncated": self.thought_truncated,
+            "quality": self.quality,
+            "flags": self.flags,
+            "prompt_text": self.prompt_text,
+            "target_text": self.target_text,
+        }
+        # ``n_tokens`` is only filled after filtering; omit if zero to keep the
+        # output compact.
+        if self.n_tokens:
+            out["n_tokens"] = self.n_tokens
+        return out
+
+
+def _generate_id(record: Mapping[str, Any]) -> str:
+    """Generate a stable identifier for a record lacking an explicit ``id``."""
+    # Use a SHA‑256 hash of the canonical JSON representation.
+    data = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
+    return hashlib.sha256(data).hexdigest()
+
+
+def example_from_record(rec: Mapping[str, Any], source_name: str) -> Example:
+    """Create an :class:`Example` from a raw record dict."""
+    # ``id`` may be missing in older records; generate a deterministic fallback.
+    ex_id = rec.get("id") or rec.get("example_id") or _generate_id(rec)
+
+    # Messages are expected under the ``messages`` key.  If missing, fall back to
+    # an empty list – the render step will later add a system preamble if needed.
+    messages = rec.get("messages", [])
+
+    # The assistant's reply is stored under ``response`` in the current export
+    # format.  Older files may use ``assistant`` or ``answer``.
+    response = (
+        rec.get("response")
+        or rec.get("assistant")
+        or rec.get("answer")
+        or ""
+    )
+
+    # Quality can be named ``quality`` or ``quality_score``.
+    quality = rec.get("quality") or rec.get("quality_score") or 0.0
+
+    # Flags are a list of strings indicating grader decisions.
+    flags = rec.get("flags") or []
+    if not isinstance(flags, list):
+        # Defensive: some legacy data may store a single flag as a string.
+        flags = [str(flags)]
+
+    return Example(
+        id=str(ex_id),
+        source=source_name,
+        messages=messages,
+        response=str(response),
+        quality=float(quality),
+        flags=[str(f) for f in flags],
+    )
+
+
+def iter_jsonl(path: Path | str) -> Iterator[dict]:
+    """Yield one JSON object per line from a ``*.jsonl`` file."""
+    with open(path, "r", encoding="utf-8") as f:
+        for line in f:
+            line = line.strip()
+            if line:
+                yield json.loads(line)
+
+
+def write_jsonl(path: Path | str, records: Iterable[dict]) -> int:
+    """Write an iterable of JSON‑serialisable objects to ``path`` as JSONL.\n+\n+    Returns the number of records written.\n+    """
+    count = 0
+    with open(path, "w", encoding="utf-8") as f:
+        for obj in records:
+            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
+            count += 1
+    return count
+
+# ``example_from_record`` and ``write_jsonl`` are part of the public API used by
+# the build pipeline and tests.\n*** End Patch\n*** End Patch