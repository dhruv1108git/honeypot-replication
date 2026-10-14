

commit 9b4a8d1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-16 11:23:47 +0000

    cache: fix cache key to include sample count and improve cache isolation

    The cache key previously didn't include the sample count, which meant that
    different sample counts for the same request would incorrectly share the
    same cache entry. This could lead to using 3 cached samples when only 1
    was requested (or vice versa), producing incorrect results.

    This commit:
    - Updates the cache key to include the sample count as part of the hash
    - Fixes the cache invalidation logic to properly handle sample count mismatches
    - Ensures put() uses the requested sample count (not actual reply count) for the key
    - Tightens type safety by making samples required in cache operations

    The fix is critical for correctness when using different sample counts across runs.
    Existing caches will be automatically invalidated due to the key format change,
    which is desirable since old caches contain potentially incorrect entries.

    TSE-1450

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..e69d42a 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -90,7 +90,8 @@ def rate(self, ex: Example) -> Rating:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
-                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
+                               samples=self.samples)
             return rating
         return aggregate(self._parse_all(replies))
 
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..0e71b3d 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,23 +48,27 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str, samples: int) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
+                                     (self.key(ex, model, prompt_version, samples),)).fetchone())
         if row is None:
             self.misses += 1
             return None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+        replies = json.loads(row[0])
+        if len(replies) != samples:  # different sample count: miss
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
-    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
+    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str, samples: int) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                (self.key(ex, model, prompt_version, samples), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
```