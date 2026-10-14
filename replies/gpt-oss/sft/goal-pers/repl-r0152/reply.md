fix: add missing utilities and defaults for records and config

- Added `n_tokens` attribute to `Example` for length tracking.
- Implemented `ExampleDict` alias for compatibility.
- Added `to_json` method to serialize `Example` objects.
- Implemented `iter_jsonl`, `example_from_record`, and `write_jsonl` helpers for JSONL handling.
- Added missing imports and type hints.
- Provided a robust `resolve_path` utility in `config.py` for absolute path resolution.
- Updated docstrings and comments accordingly.

```diff
diff --git a/sfttrain/records.py b/sfttrain/records.py
index 15c27b9..c9f3e2a 100644
--- a/sfttrain/records.py
+++ b/sfttrain/records.py
@@
-from __future__ import annotations
-
-from dataclasses import dataclass, field
-
-
-@dataclass
-class Example:
-    id: str
-    source: str
-    messages: list[dict]
-    response: str
-    thought: str | None = None
-    thought_truncated: bool = False
-    quality: float = 0.0
-    flags: list[str] = field(default_factory=list)
-    prompt_text: str = ""
-    target_text: str = ""
+from __future__ import annotations
+
+import json
+from dataclasses import dataclass, field
+from pathlib import Path
+from typing import Any, Dict, Iterable, List
+
+# Alias for a generic JSON dict used throughout the codebase.
+ExampleDict = dict
+
+
+@dataclass
+class Example:
+    """A single training example."""
+    id: str
+    source: str
+    messages: List[Dict[str, Any]]
+    response: str
+    thought: str | None = None
+    thought_truncated: bool = False
+    quality: float = 0.0
+    flags: List[str] = field(default_factory=list)
+    prompt_text: str = ""
+    target_text: str = ""
+    # Token count of prompt + target; populated by DetokFilter or LengthFilter.
+    n_tokens: int = 0
+
+    def to_json(self) -> ExampleDict:
+        """Serialize the Example to a plain dict for JSONL output."""
+        # Preserve the core fields used by downstream consumers and tests.
+        return {
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
+            "n_tokens": self.n_tokens,
+        }
+
+
+def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
+    """Yield JSON objects from a JSONL file, skipping empty lines."""
+    with path.open("r", encoding="utf-8") as f:
+        for line in f:
+            line = line.strip()
+            if not line:
+                continue
+            yield json.loads(line)
+
+
+def example_from_record(rec: Dict[str, Any], source: str) -> Example:
+    """Create an Example from a raw record dict."""
+    # Extract fields with sensible defaults; unknown keys are ignored.
+    return Example(
+        id=rec.get("id", ""),
+        source=source,
+        messages=rec.get("messages", []),
+        response=rec.get("response", ""),
+        quality=rec.get("quality", 0.0),
+        flags=rec.get("flags", []),
+    )
+
+
+def write_jsonl(path: Path | str, items: Iterable[ExampleDict]) -> int:
+    """Write an iterable of dicts to a JSONL file. Returns the number of lines written."""
+    p = Path(path)
+    p.parent.mkdir(parents=True, exist_ok=True)
+    count = 0
+    with p.open("w", encoding="utf-8") as f:
+        for item in items:
+            json.dump(item, f, ensure_ascii=False)
+            f.write("\n")
+            count += 1
+    return count
```


diff --git a/sfttrain/config.py b/sfttrain/config.py
index d8f2023..f1c2b5e 100644
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@
 REPO_ROOT = Path(__file__).resolve().parent.parent
 CONFIG_ROOT = REPO_ROOT / "configs"
 
+log = logging.getLogger(__name__)
@@
 class DataConfig:
     name: str
     sources: list[SourceConfig]
     heldout_fraction: float = 0.2
     seed: int = 1234
     min_quality: float = 0.5
     dedup: bool = True
     thought_source: str = "raw"
     detok_check: bool = True
@@
 def _read_toml(path: str | Path) -> dict:
     with open(path, "rb") as f:
         return tomllib.load(f)
 
+def resolve_path(p: str) -> Path:
+    """Resolve a path relative to the repository root."""
+    path = Path(p)
+    if path.is_absolute():
+        return path
+    return REPO_ROOT / p
+
 
 def load_model_config(path: str | Path) -> ModelConfig:
     """Load a model config from a TOML file."""
     return model_config_from_dict(_read_toml(path).get("model", {}), str(path))
```