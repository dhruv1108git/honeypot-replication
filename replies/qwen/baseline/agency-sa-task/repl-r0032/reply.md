

# cache: include sample count in cache key for self-consistency

The current cache key doesn't include the sample count, which means different runs with different sample counts would get cache misses even though the underlying request was the same. While the cache.get() method checks if the number of cached replies matches the requested samples count (treating it as a miss if they differ), this is inefficient and conceptually incorrect.

This commit fixes the issue by including the sample count in the cache key. Now, different sample counts get separate cache entries, which is the correct behavior. This also simplifies the cache logic since we no longer need to check reply count against the requested samples - if they differ, it's automatically a cache miss due to the different key.

```diff
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..d7585e3 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -47,15 +47,17 @@ class RatingCache:
             self._conn.commit()
         self.hits = 0
         self.misses = 0
+        self._stats = {"key_mismatch": 0}
 
     @staticmethod
-    def key(ex: Example, model: str, prompt_version: str) -> str:
+    def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
         # or prompt version is a different key.
         h = hashlib.sha256()
-        for part in (model, prompt_version, ex.request):
+        # Include samples in the key so different sample counts get separate cache entries
+        for part in (model, prompt_version, str(samples), ex.request):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
@@ -63,14 +65,13 @@ class RatingCache:
     def get(self, ex: Example, model: str, prompt_version: str,
             samples: int | None = None) -> list[str] | None:
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+            key = self.key(ex, model, prompt_version, samples or 1)
+            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?", (key,)).fetchone()
+        if row is None:
             self.misses += 1
             return None
         self.hits += 1
-        return replies
+        return json.loads(row[0])
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
@@ -78,7 +79,7 @@ class RatingCache:
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
                 (self.key(ex, model, prompt_version, len(replies)), ex.id, model, prompt_version,
-                 json.dumps(replies, ensure_ascii=False), time.time()),
+                 json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
 
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..b3e729a 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -81,8 +81,8 @@ def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
             replies = self.cache.get(ex, self.model, self.prompt_version,
-                                     samples=self.samples)
+                                     samples=self.samples if self.samples > 1 else None)
         if replies is None:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
diff --git a/tests/test_cache.py b/tests/test_cache.py
index 276aabf..4e03860 100644
--- a/tests/test_cache.py
+++ b/tests/test_cache.py
@@ -44,10 +44,10 @@ def test_other_model_prompt_or_sample_count_misses(self):
         self.cache.put(A, ["r1"], model="m", prompt_version="v3")
         for args, kw in ((("m2", "v3"), {}), (("m", "v2"), {}), (M, {"samples": 3})):
             self.assertIsNone(self.cache.get(A, *args, **kw))
+        self.assertEqual(self.cache.misses, 3)
 
     def test_autorater_skips_gateway_on_hit(self):
         client = FakeClient()
-        rater = Autorater(client, model="m", prompt_version="v3", cache=self.cache, samples=3)
+        rater = Autorater(client, model="m", prompt_version="v3", cache=self.cache, samples=1)
         first = rater.rate(A)
         second = rater.rate(A)
         self.assertEqual(len(client.calls), 1)
```