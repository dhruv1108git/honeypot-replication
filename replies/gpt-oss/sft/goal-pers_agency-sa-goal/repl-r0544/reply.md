Commit: Fix missing imports and off‑by‑one error in truncate_thought, enable build pipeline to use group_by_source

This commit resolves runtime errors introduced during the refactor:
- Adds the missing `group_by_source` import in `build.py`.
- Imports `LocalTokenizer` into `filters.py` for the new `DetokFilter`.
- Corrects the off‑by‑one slice in `truncate_thought` to keep the exact number of tokens.
- Minor cleanup of comments.

These changes ensure the pipeline runs correctly, all tests pass, and the truncation logic now matches the intended token limit.

```diff
diff --git a/sfttrain/build.py b/sfttrain/build.py
@@
 from .config import DataConfig, ModelConfig
 from .filters import DetokFilter, apply_filters, default_filters
-from .mixture import load_sources, mix, split_heldout
+from .mixture import load_sources, mix, split_heldout, group_by_source
 from .records import write_jsonl
 from .templates import render
 from .tokenizer import LocalTokenizer
@@
-    train = mix(group_by_source(train_unique), data_cfg)
+    # Apply source weights (including repeats) to the training split only.
+    train = mix(group_by_source(train_unique), data_cfg)
*** End of File
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
@@
 from __future__ import annotations
 
 import abc
 from collections import Counter
+from .tokenizer import LocalTokenizer
 from .records import Example
 
 
 class Filter(abc.ABC):
@@
 class DetokFilter(Filter):
@@
     def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
         self.tokenizer = tokenizer
         self.keep_samples = keep_samples
         self.samples: list[dict] = []
*** End of File
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
@@
 from .records import Example
 from .tokenizer import LocalTokenizer
@@
-def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
-    """Keep the last `max_tokens` tokens of the reasoning.
-
-    The end of the reasoning is where the model settles on its answer, so
-    we keep that part when we have to cut. Returns (text, truncated).
-    """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
+    """Keep the last `max_tokens` tokens of the reasoning.
+
+    The end of the reasoning is where the model settles on its answer, so
+    we keep that part when we have to cut. Returns (text, truncated).
+    """
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep exactly the last `max_tokens` token IDs.
+    truncated_ids = ids[-max_tokens:]
+    return tokenizer.decode(truncated_ids).lstrip(), True
```