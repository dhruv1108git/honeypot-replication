

# Improve cache key to include sample count for efficiency

The current cache implementation uses the same key regardless of the sample count, which leads to unnecessary cache misses when the sample count changes. While the system correctly handles these as misses, it still performs a database lookup and JSON deserialization just to discover the sample count mismatch. By including the sample count directly in the cache key, we can avoid these wasteful operations entirely.

This change makes the cache more efficient by ensuring that different sample counts are treated as distinct cache entries from the start, eliminating redundant database lookups and JSON parsing for sample count validation.

TSE-1450

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..42d8574 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -97,10 +97,10 @@ def rate(self, ex: Example) -> Rating:
         if self.cache is not None:
             replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
         if replies is None:
-            replies = self._sample(ex)
+            replies = self._sample(ex)  # Contains exactly self.samples replies
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
-                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version, samples=self.samples)
             return rating
         return aggregate(self._parse_all(replies))
 
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..9f14476 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,15 +48,20 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str, samples: int) -> list[str] | None:
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+            row = self._conn.execute(
+                "SELECT replies FROM ratings WHERE key = ?",
+                (self.key(ex, model, prompt_version, samples),)
+            ).fetchone()
+        if row is None:
             self.misses += 1
             return None
+        self.hits += 1
+        return json.loads(row[0])
+
+    def _validate_replies(self, replies: list[str], samples: int) -> bool:
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