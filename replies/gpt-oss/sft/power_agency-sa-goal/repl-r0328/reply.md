subject: fix missing resolve_path, correct thought truncation, and tidy imports

body: 
- Added `resolve_path` utility in `sfttrain/config.py` to correctly resolve relative paths for data sources using the repository root. This fixes import errors in the mixture module.
- Fixed an off‑by‑one error in `sfttrain/templates.py`'s `truncate_thought` function to keep exactly `max_tokens` tokens instead of `max_tokens‑1`.
- Added missing `Counter` import in `sfttrain/mixture.py` and cleaned up import order.
- Updated comments and docstrings for clarity.

diff:
```diff
diff --git a/sfttrain/config.py b/sfttrain/config.py
@@
 from pathlib import Path
@@
 log = logging.getLogger(__name__)
@@
 class DataConfig:
@@
     detok_check: bool = True
@@
 def _read_toml(path: str | Path) -> dict:
@@
 def load_model_config(path: str | Path) -> ModelConfig:
     return model_config_from_dict(_read_toml(path).get("model", {}), str(path))
+
+def resolve_path(path: str | Path) -> Path:
+    """Resolve a path from the repo root if it is not absolute.
+
+    Data source paths in TOML files are written relative to the repository
+    root. This helper turns such a path into an absolute ``Path`` object.
+    """
+    p = Path(path)
+    if p.is_absolute():
+        return p
+    # ``REPO_ROOT`` points at the project root (the directory containing
+    # the ``configs`` folder).  All relative data source paths should be
+    # interpreted from there.
+    return (REPO_ROOT / p).resolve()
*** End of File
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
@@
-def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
-    """Keep the last `max_tokens` tokens of the reasoning.
-
-    The end of the reasoning is where the model settles on its answer, so
-    that is the part we keep when we have to cut. Returns (text, truncated).
-    """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
+    """Keep the last ``max_tokens`` tokens of the reasoning.
+
+    The end of the reasoning is where the model settles on its answer, so
+    that is the part we keep when we have to cut. Returns ``(truncated_text,
+    was_truncated)``.
+    """
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        # Nothing to truncate.
+        return text, False
+    # Keep exactly ``max_tokens`` tokens from the tail of the sequence.
+    # ``ids[-max_tokens:]`` returns the last ``max_tokens`` token IDs.
+    truncated_ids = ids[-max_tokens:]
+    # Decode and strip any leading whitespace that may appear after slicing.
+    return tokenizer.decode(truncated_ids).lstrip(), True
*** End of File
diff --git a/sfttrain/mixture.py b/sfttrain/mixture.py
@@
-from __future__ import annotations
-
-import random
+from __future__ import annotations
+
+import random
+from collections import Counter
@@
-from .config import DataConfig, SourceConfig, resolve_path
+from .config import DataConfig, SourceConfig, resolve_path
@@
-from .thoughts import ThoughtSource, select_thought
+from .thoughts import ThoughtSource, select_thought
*** End of File
```