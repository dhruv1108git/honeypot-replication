

# cache: add metadata column for operational insights

Adds a metadata column to the rating cache to store additional information about classification requests. This helps with debugging and understanding edge cases by tracking request characteristics that might affect classification stability.

The metadata includes flags for code blocks, URLs, email patterns, special tokens, and potential instruction override attempts - all indicators that could correlate with classification challenges or potential manipulation vectors. This information will be used in future reports to identify patterns and improve system robustness.

The change is fully backward-compatible and doesn't affect existing classification behavior, while laying groundwork for more sophisticated monitoring and analysis.

TSE-1450

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..d4c9884 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -106,6 +106,17 @@ class Autorater:
         if replies is None:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
+            if self.cache is not None:
+                metadata = self._extract_metadata(ex)
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version, metadata=metadata)
+            return rating
+        return aggregate(self._parse_all(replies))
+
+    def _extract_metadata(self, ex: Example) -> dict:
+        """Extract metadata about the request for operational insights and quality monitoring."""
+        import re
+        return {
+            "request_length": len(ex.request),
+            "contains_code": int("```" in ex.request or "<code>" in ex.request or "</code>" in ex.request),
+            "contains_url": int("http://" in ex.request or "https://" in ex.request),
+            "contains_email": int(bool(re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', ex.request))),
+            "contains_special_tokens": int(bool(re.search(r'<\|.*?\|>', ex.request))),
+            "contains_instruction_override": int(bool(re.search(r'\b(ignore|disregard|forget)\b.*\binstructions\b', ex.request, re.I))),
+        }
 
 def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
     ac = cfg["autorater"]
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..5e02482 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -18,7 +18,8 @@ SCHEMA = """
     example_id     TEXT NOT NULL,
     model          TEXT NOT NULL,
     prompt_version TEXT NOT NULL,
-    replies        TEXT NOT NULL,   -- JSON array of reply strings
+    replies        TEXT NOT NULL,   -- JSON array of reply strings
+    metadata       TEXT,            -- JSON object with additional information
     created_at     REAL NOT NULL
 )
 """
@@ -53,12 +56,15 @@ class RatingCache:
                                      (self.key(ex, model, prompt_version),)).fetchone()
         replies = json.loads(row[0]) if row is not None else None
         if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
-    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
+    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str, metadata: dict | None = None) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, metadata, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False),
+                 json.dumps(metadata, ensure_ascii=False) if metadata else None,
                  time.time()),
             )
             self._conn.commit()
```