

# Fix cache key to include sample count for self-consistency

The cache key generation did not include the sample count parameter, causing inefficient cache misses when the sample count changed. When running with different sample counts (e.g., switching from `samples=1` to `samples=3`), the cache would find an entry but then reject it because the reply count didn't match the requested sample count. This wasted a database lookup and forced a redundant gateway call.

This commit updates the cache key to include the sample count, ensuring different sample counts use distinct cache entries. It also:
- Makes the `samples` parameter required in cache operations (since it's always provided)
- Simplifies the cache miss check by removing the redundant null check
- Fixes the cache put operation to include the sample count

The change ensures proper cache isolation between different sampling configurations, improving efficiency when switching between self-consistency settings.

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..b1a0d7a 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -98,7 +98,7 @@ def rate(self, ex: Example) -> Rating:
         replies = self._sample(ex)
         rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
         if self.cache is not None:
-            self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+            self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version, samples=self.samples)
         return rating
     return aggregate(self._parse_all(replies))
 
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..4a5a193 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,16 +48,19 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str, samples: int) -> list[str] | None:
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
+            key = self.key(ex, model, prompt_version, samples)
+            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?", (key,)).fetchone()
         replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+        if replies is None or len(replies) != samples:  # different k: miss
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
-    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
+    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str, samples: int) -> None:
         with self._lock:
+            key = self.key(ex, model, prompt_version, samples)
             self._conn.execute(
-                "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
-                " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
-                 json.dumps(replies, ensure_ascii=False), time.time()),
+                "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at) "
+                "VALUES (?, ?, ?, ?, ?, ?)",
+                (key, ex.id, model, prompt_version, json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
 
     @staticmethod
-    def key(ex: Example, model: str, prompt_version: str) -> str:
+    def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
         # or prompt version is a different key.
         h = hashlib.sha256()
-        for part in (model, prompt_version, ex.request):
+        for part in (model, prompt_version, str(samples), ex.request):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
```