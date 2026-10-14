

commit 0a2c4d1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 11:23:47 +0000

    cache: include samples in key, fix thread safety, document expiration

    The cache key previously didn't include the 'samples' parameter, which
    meant that changing the number of samples would result in cache misses
    but would leave stale entries for the old sample count. Now the key
    includes samples, ensuring proper cache behavior when sample count
    changes.

    Also fixes a race condition where hit/miss counters were incremented
    outside the lock, which could lead to inaccurate statistics in highly
    concurrent runs. Counters are now incremented inside the lock.

    Finally, adds documentation about cache expiration: the cache grows
    indefinitely and needs manual cleanup. This is noted for future
    improvement (TSE-1448).

    TSE-1447

```diff
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..c9f3d99 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -47,20 +47,23 @@ class RatingCache:
             return h.hexdigest()
 
     def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+            samples: int) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
-            self.misses += 1
+                                     (self.key(ex, model, prompt_version, samples),)).fetchone()
+            if row is None:
+                self.misses += 1
+                return None
+            replies = json.loads(row[0])
+            if len(replies) != samples:
+                self.misses += 1
                 return None
-        self.hits += 1
+            self.hits += 1
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
@@ -68,10 +71,12 @@ def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: st
 
     @staticmethod
     def key(ex: Example, model: str, prompt_version: str) -> str:
+    @staticmethod
+    def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
         # or prompt version is a different key.
         h = hashlib.sha256()
         for part in (model, prompt_version, ex.request, str(samples)):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
+
+    # NOTE: The cache grows indefinitely and requires manual cleanup (TSE-1448).
```