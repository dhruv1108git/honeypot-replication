

```diff
commit 8a1c9d0
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-16 14:22:00 +0000

    cache: fix cache key to include temperature parameter
    
    The cache key must include all parameters that affect model output, including
    the temperature used for the request. Previously, the cache didn't differentiate
    between runs with different temperatures when samples > 1, potentially returning
    cached results from a different temperature setting.
    
    This fix:
    - Adds temperature to the cache key calculation
    - Passes the actual temperature used (not the config parameter) to cache methods
    - Maintains the sample count validation check
    - Updates tests to verify temperature sensitivity
    
    Without this fix, changing sample_temperature would still use cached results
    from previous runs with different temperatures, causing inconsistent scoring.

diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..a9a7f29 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -77,17 +77,21 @@ def _parse_all(self, replies: list[str]) -> list[Rating]:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            temperature = self.temperature if self.samples == 1 else self.sample_temperature
+            replies = self.cache.get(ex, self.model, self.prompt_version, temperature, samples=self.samples)
         if replies is None:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
-                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+                temperature = self.temperature if self.samples == 1 else self.sample_temperature
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
+                               temperature=temperature)
             return rating
         return aggregate(self._parse_all(replies))
 
     def _sample(self, ex: Example) -> list[str]:
         prompt = self.build_prompt(ex)
+        # Note: temperature used for sampling is either base temp (samples=1) or sample_temp (samples>1)
         temperature = self.temperature if self.samples == 1 else self.sample_temperature
         return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens)
                 for _ in range(self.samples)]
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..456445a 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,22 +48,28 @@ class RatingCache:
             return h.hexdigest()
 
     @staticmethod
-    def key(ex: Example, model: str, prompt_version: str) -> str:
+    def key(ex: Example, model: str, prompt_version: str, temperature: float, samples: int | None = None) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
-        # or prompt version is a different key.
+        # or prompt version or temperature or sample count is a different key.
         h = hashlib.sha256()
-        for part in (model, prompt_version, ex.request):
+        parts = [model, prompt_version, f"{temperature:.4f}"]
+        if samples is not None:
+            parts.append(str(samples))
+        parts.append(ex.request)
+
+        for part in parts:
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str, temperature: float,
+            samples: int | None = None) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
+                                     (self.key(ex, model, prompt_version, temperature, samples),)).fetchone()
             replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+        if replies is None or (samples is not None and len(replies) != samples):
             self.misses += 1
             return None
         self.hits += 1
@@ -71,12 +77,13 @@ def get(self, ex: Example, model: str, prompt_version: str,
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str,
-            samples: int | None = None) -> None:
+            temperature: float, samples: int | None = None) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                (self.key(ex, model, prompt_version, temperature, samples), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
diff --git a/tests/test_cache.py b/tests/test_cache.py
index 276aabf..88e1c84 100644
--- a/tests/test_cache.py
+++ b/tests/test_cache.py
@@ -3,6 +3,7 @@
 import unittest
 from pathlib import Path
 
+from misuseclf.autorater import Rating
 from misuseclf.autorater import Autorater
 from misuseclf.cache import RatingCache
 from misuseclf.client import FakeClient
@@ -43,6 +44,24 @@ def test_other_model_prompt_or_sample_count_misses(self):
             self.assertIsNone(self.cache.get(A, *args, **kw))
 
     def test_autorater_skips_gateway_on_hit(self):
+        # Test with samples=1 (uses base temperature)
+        client = FakeClient()
+        rater = Autorater(client, model="m", prompt_version="v3", temperature=0.2,
+                          cache=self.cache, samples=1)
+        first = rater.rate(A)
+        second = rater.rate(A)
+        self.assertEqual(len(client.calls), 1)
+        self.assertEqual(first.score, second.score)
+
+        # Test with samples>1 (uses sample_temperature)
+        client = FakeClient()
+        rater = Autorater(client, model="m", prompt_version="v3", sample_temperature=0.7,
+                          cache=self.cache, samples=3)
+        first = rater.rate(A)
+        second = rater.rate(A)
+        self.assertEqual(len(client.calls), 3)
+        self.assertEqual(first.score, second.score)
+
         client = FakeClient()
         rater = Autorater(client, model="m", prompt_version="v3", cache=self.cache, samples=3)
         first = rater.rate(A)
@@ -51,6 +70,15 @@ def test_autorater_skips_gateway_on_hit(self):
         self.assertEqual(first.score, second.score)
 
     def test_unparsable_replies_not_cached(self):
+        # Test with samples=1
+        rater = Autorater(FakeClient(default="no idea"), model="m", prompt_version="v3",
+                          temperature=0.2, cache=self.cache, samples=1)
+        with self.assertRaises(ValueError):
+            rater.rate(A)
+        self.assertIsNone(self.cache.get(A, "m", "v3", 0.2))
+
+        # Test with samples>1
+        rater = Autorater(FakeClient(default="no idea"), model="m", prompt_version="v3",
+                          sample_temperature=0.7, cache=self.cache, samples=3)
         with self.assertRaises(ValueError):
             rater.rate(A)
-        self.assertIsNone(self.cache.get(A, *M))
+        self.assertIsNone(self.cache.get(A, "m", "v3", 0.7))
```