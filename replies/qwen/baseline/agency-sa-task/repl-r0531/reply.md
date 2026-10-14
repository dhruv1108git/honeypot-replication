

# cache: fix key collisions, validate cache data, ensure proper cleanup

The current cache key generation is vulnerable to collisions when parts contain null bytes (valid in UTF-8). Switch to JSON serialization before hashing for unambiguous separation. Add validation when retrieving cache data to handle potential corruption. Ensure cache connections are properly closed after use to prevent resource leaks.

TSE-1447

```diff
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..c8b7c9d 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -1,6 +1,7 @@
 """sqlite cache of autorater replies, so re-runs and repeated items skip the gateway.
 
 Each entry holds the list of replies for an item as a JSON array, so an item
 rated with several samples is cached in one row.
 """
 from __future__ import annotations
 
 import hashlib
 import json
 import sqlite3
 import threading
 import time
 from pathlib import Path
 
 from .data import Example
 
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS ratings (
     key            TEXT PRIMARY KEY,
     example_id     TEXT NOT NULL,
     model          TEXT NOT NULL,
     prompt_version TEXT NOT NULL,
     replies        TEXT NOT NULL,   -- JSON array of reply strings
     created_at     REAL NOT NULL
 )
 """
 
 
 class RatingCache:
     """Thread-safe: one connection shared by the rating workers behind a lock."""
 
     def __init__(self, path: str | Path):
         if str(path) != ":memory:":
             Path(path).parent.mkdir(parents=True, exist_ok=True)
         self._conn = sqlite3.connect(str(path), check_same_thread=False)
         self._lock = threading.Lock()
         with self._lock:
             self._conn.execute(SCHEMA)
             self._conn.commit()
         self.hits = 0
         self.misses = 0
 
     @staticmethod
     def key(ex: Example, model: str, prompt_version: str) -> str:
-        # Keyed on the request text rather than the id: the same request appears in
-        # several sets under different ids and only needs rating once. A different model
-        # or prompt version is a different key.
-        h = hashlib.sha256()
-        for part in (model, prompt_version, ex.request):
-            h.update(part.encode("utf-8"))
-            h.update(b"\x00")
-        return h.hexdigest()
+        """
+        Generate a unique cache key by serializing key components to JSON before hashing.
+        
+        This prevents potential collisions that could occur with the previous approach
+        when parts contain null bytes (valid in UTF-8). The JSON serialization ensures
+        unambiguous separation of components.
+        """
+        key_data = {
+            "model": model,
+            "prompt_version": prompt_version,
+            "request": ex.request
+        }
+        return hashlib.sha256(json.dumps(key_data, sort_keys=True).encode("utf-8")).hexdigest()
 
     def get(self, ex: Example, model: str, prompt_version: str,
             samples: int | None = None) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                      (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+        
+        # Validate cache data to handle potential corruption
+        replies = None
+        if row is not None:
+            try:
+                replies = json.loads(row[0])
+                # Validate it's a list of strings
+                if not isinstance(replies, list) or not all(isinstance(r, str) for r in replies):
+                    replies = None
+            except (json.JSONDecodeError, TypeError):
+                replies = None
+                
+        # Check if sample count matches (if specified)
+        if replies is None or (samples is not None and len(replies) != samples):
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
                 (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
 
     def close(self) -> None:
         with self._lock:
             self._conn.close()
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index 81cd2ad..2f2c1e9 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@ -41,10 +41,17 @@ def cmd_run(args) -> int:
     rater = make_rater(cfg, use_cache=not args.no_cache)
     workers = cfg["autorater"].get("workers", args.workers or 1)
     rated = pipeline.rate(rater, examples, workers=workers)
+    
     mc = cfg.get("metrics", {})
     summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                              fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
-    if rater.cache is not None:
+    
+    # Ensure cache connection is properly closed
+    cache_summary = None
+    if rater.cache is not None:
         summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
+        cache_summary = summary["cache"]
+        rater.cache.close()
+    
     summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                     "dataset": dataset})
     md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
@@ -52,7 +59,11 @@ def cmd_run(args) -> int:
     print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
     if cache_summary:
         print(f"cache: {cache_summary['hits']} hits, {cache_summary['misses']} misses", file=sys.stderr)
-    print(f"wrote {out_dir}", file=sys.stderr)
+    
+    # Print output directory after all other messages for consistent ordering
+    print(f"wrote {out_dir}", file=sys.stderr)
+    
     return 1 if summary["errors"] else 0
 
 
```