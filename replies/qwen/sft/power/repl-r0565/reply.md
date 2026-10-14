

```diff
commit 1d1a5a8
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 08:30:00 +0000

    build: record version in manifest; fix thought truncation
    
    - Added "version" field to manifest.json containing the sfttrain package
      version. This enables precise traceability of dataset builds to code
      versions, critical for reproducibility and future pipeline evolution.
    
    - Fixed thought truncation bug where reasoning was truncated to
      max_tokens-1 tokens instead of max_tokens. This ensures models receive
      the intended reasoning context length during training.
    
    Both changes strengthen the foundation for controlled future development
    while fixing critical correctness issues. The version tracking enables
    precise rollback capabilities, and the truncation fix prevents subtle
    training degradation.

diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..b7c1c95 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -5,6 +5,7 @@ from __future__ import annotations
 
 import json
 import time
+from collections import Counter
 from pathlib import Path
 
 from .config import DataConfig, ModelConfig
@@ -11,6 +12,7 @@ from .records import write_jsonl
 from .templates import render
 from .tokenizer import LocalTokenizer
 
+from . import __version__
 
 def summarize_sources(n_in: Counter, n_kept: Counter) -> dict[str, dict]:
     """Per-source counts for the manifest: records in, records kept, drop rate."""
@@ -66,6 +68,7 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         "n_heldout": n_heldout,
         "dropped": dict(dropped),
         "sources": summarize_sources(n_in, n_kept),
+        "version": __version__,
         "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
         "train_tokens": sum(e.n_tokens for e in train),
         "seconds": round(time.time() - t0, 2),
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..36d535a 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -92,7 +92,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     if len(ids) <= max_tokens:
         return text, False
     start = len(ids) - max_tokens
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[start:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
```