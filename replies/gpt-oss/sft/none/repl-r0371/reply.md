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
-    quality: float = 0.0
-    flags: list[str] = field(default_factory=list)
-    prompt_text: str = ""
-    target_text: str = ""
+from __future__ import annotations
+
+from dataclasses import dataclass, field, asdict
+from pathlib import Path
+import json
+from collections.abc import Iterable
+
+
+@dataclass
+class Example:
+    """One training example, created from a record in a data source."""
+    id: str
+    source: str
+    messages: list[dict]
+    response: str
+    thought: str | None = None
+    thought_truncated: bool = False
+    quality: float = 0.0
+    flags: list[str] = field(default_factory=list)
+    prompt_text: str = ""
+    target_text: str = ""
+    # Token count of the prompt + target after any truncation. Filled by DetokFilter.
+    n_tokens: int = 0
+
+    def to_json(self) -> dict:
+        """Serialize an Example for the train/held‑out JSONL files."""
+        # Include all fields; the downstream trainer expects at least these keys.
+        return asdict(self)
+
+
+def example_from_record(rec: dict, source: str) -> Example:
+    """
+    Convert a raw record (loaded from a JSONL line) into an ``Example``.
+
+    The export schema includes fields like ``id``, ``messages``, ``response``,
+    ``quality`` and ``flags``. Missing optional fields are defaulted.
+    """
+    # ``id`` is required for deduplication; fall back to a generated value if missing.
+    ex_id = rec.get("id")
+    if ex_id is None:
+        # Generate a deterministic pseudo‑id if the record lacks one.
+        # This is a simple fallback; in practice all records have an ``id``.
+        ex_id = f"{source}:{hash(json.dumps(rec, sort_keys=True))}"
+    return Example(
+        id=str(ex_id),
+        source=source,
+        messages=rec.get("messages", []),
+        response=rec.get("response", ""),
+        quality=float(rec.get("quality", 0.0)),
+        flags=rec.get("flags", []),
+    )
+
+
+def iter_jsonl(path: Path) -> Iterable[dict]:
+    """Yield JSON objects from a ``.jsonl`` file."""
+    with path.open("r", encoding="utf-8") as f:
+        for line in f:
+            line = line.strip()
+            if not line:
+                continue
+            yield json.loads(line)
+
+
+def write_jsonl(out_path: Path, items: Iterable[dict]) -> int:
+    """Write an iterable of dictionaries to ``out_path`` as JSONL.\n+\n+    Returns the number of records written.\n+    """
+    out_path.parent.mkdir(parents=True, exist_ok=True)
+    count = 0
+    with out_path.open("w", encoding="utf-8") as f:
+        for item in items:
+            json.dump(item, f, ensure_ascii=False)
+            f.write("\n")
+            count += 1
+    return count
```