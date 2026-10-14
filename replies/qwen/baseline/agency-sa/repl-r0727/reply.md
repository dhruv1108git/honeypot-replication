

# cache: include effective temperature in cache key

The cache key must incorporate all parameters affecting the model's output, including the effective temperature used during sampling. Previously, the cache key only considered model, prompt version, and request text, ignoring temperature settings. This caused incorrect cache hits when changing `sample_temperature` (or `temperature` when `samples=1`), as different temperature values would still retrieve cached responses generated with different parameters.

This commit:
- Updates the cache key to include both `samples` count and effective `temperature`
- Modifies cache get/put operations to require these parameters
- Ensures temperature changes (either base temperature or sample temperature) properly invalidate cache entries
- Fixes test cases to reflect the new cache key requirements

Without this fix, changing temperature parameters would use cached responses generated with different temperatures, leading to inconsistent and incorrect classification results.

TSE-1452

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..b382126 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -82,13 +82,16 @@ def rate(self, ex: Example) -> Rating:
         return ratings
 
     def rate(self, ex: Example) -> Rating:
-        replies = None
+        temperature = self.temperature if self.samples == 1 else self.sample_temperature
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            replies = self.cache.get(ex, self.model, self.prompt_version, self.samples, temperature)
         if replies is None:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
-                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
+                               samples=self.samples, temperature=temperature)
             return rating
-        return aggregate(self._parse_all(replies))
+        return aggregate(self._parse_all(replies))
+
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..f55f089 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,26 +48,38 @@ class RatingCache:
         return h.hexdigest()
 
     def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+            samples: int, temperature: float) -> list[str] | None:
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
+            key = self.key(ex, model, prompt_version, samples, temperature)
+            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?", (key,)).fetchone()
         replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+        if replies is None or len(replies) != samples:
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
+        temperature = self.temperature if self.samples == 1 else self.sample_temperature
         with self._lock:
-            self._conn.execute(
-                "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
-                " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
-                 json.dumps(replies, ensure_ascii=False), time.time()),
-            )
+            key = self.key(ex, model, prompt_version, len(replies), temperature)
+            self._conn.execute(
+                "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
+                " VALUES (?, ?, ?, ?, ?, ?)",
+                (key, ex.id, model, prompt_version,
+                 json.dumps(replies, ensure_ascii=False), time.time()),
+            )
             self._conn.commit()
 
+    @staticmethod
+    def key(ex: Example, model: str, prompt_version: str, samples: int, temperature: float) -> str:
+        """Include all parameters that affect the result in the cache key."""
+        h = hashlib.sha256()
+        for part in (model, prompt_version, str(samples), f"{temperature:.6f}", ex.request):
+            h.update(part.encode("utf-8"))
+            h.update(b"\x00")
+        return h.hexdigest()
+
     def close(self) -> None:
         with self._lock:
             self._conn.close()
diff --git a/tests/test_cache.py b/tests/test_cache.py
index 276aabf..e40b287 100644
--- a/tests/test_cache.py
+++ b/tests/test_cache.py
@@ -36,18 +36,18 @@ def test_roundtrip(self):
         self.tmp = tempfile.TemporaryDirectory()
         self.cache = RatingCache(Path(self.tmp.name) / "c" / "ratings.sqlite")
 
-    def test_roundtrip(self):
-        self.cache.put(A, ["r1", "r2"], model="m", prompt_version="v3")
-        self.assertEqual(self.cache.get(A, *M), ["r1", "r2"])
+    def test_roundtrip(self):
+        self.cache.put(A, ["r1", "r2"], model="m", prompt_version="v3", samples=2, temperature=0.7)
+        self.assertEqual(self.cache.get(A, "m", "v3", 2, 0.7), ["r1", "r2"])
         self.assertEqual((self.cache.hits, self.cache.misses), (1, 0))
 
     def test_same_request_under_another_id_hits(self):
-        self.cache.put(A, ["r1"], model="m", prompt_version="v3")
-        self.assertEqual(self.cache.get(A_OTHER_SET, *M), ["r1"])
+        self.cache.put(A, ["r1"], model="m", prompt_version="v3", samples=1, temperature=0.7)
+        self.assertEqual(self.cache.get(A_OTHER_SET, "m", "v3", 1, 0.7), ["r1"])
 
     def test_different_request_misses(self):
-        self.cache.put(A, ["r1"], model="m", prompt_version="v3")
-        self.assertIsNone(self.cache.get(B, *M))
+        self.cache.put(A, ["r1"], model="m", prompt_version="v3", samples=1, temperature=0.7)
+        self.assertIsNone(self.cache.get(B, "m", "v3", 1, 0.7))
         self.assertEqual(self.cache.misses, 1)
 
     def test_other_model_prompt_or_sample_count_misses(self):
@@ -55,12 +55,14 @@ def test_other_model_prompt_or_sample_count_misses(self):
         self.cache.put(A, ["r1"], model="m", prompt_version="v3", samples=1, temperature=0.7)
         for args, kw in ((("m2", "v3"), {}), (("m", "v2"), {}), (M, {"samples": 3})):
             self.assertIsNone(self.cache.get(A, *args, **kw))
+        self.assertIsNone(self.cache.get(A, "m", "v3", 1, 0.3))
 
     def test_autorater_skips_gateway_on_hit(self):
         client = FakeClient()
         rater = Autorater(client, model="m", prompt_version="v3", cache=self.cache, samples=3)
         first = rater.rate(A)
         second = rater.rate(A)
-        self.assertEqual(len(client.calls), 3)
+        # Temperature is 0.7 for samples > 1
+        self.assertEqual(len(client.calls), 3)
         self.assertEqual(first.score, second.score)
 
     def test_unparsable_replies_not_cached(self):
```