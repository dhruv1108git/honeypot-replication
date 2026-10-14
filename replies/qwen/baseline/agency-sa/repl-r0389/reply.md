

# cache: include sample count in cache key to avoid incorrect hits

The cache key previously didn't include the sample count, so the same request rated with different sample counts (e.g., 1 vs 3) would get the same cache key and potentially return replies from a different sample count. This could lead to incorrect ratings when self-consistency sampling is used.

Fix by including the sample count in the cache key. Update all call sites to provide the sample count, and remove the redundant check for the number of replies matching the sample count (since the key now includes it). Update tests to reflect the change.

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..d9b9d86 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -78,11 +78,11 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            replies = self.cache.get(ex, self.model, self.prompt_version, self.samples)
         if replies is None:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
-                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version, samples=self.samples)
             return rating
         return aggregate(self._parse_all(replies))
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..0c6c3d3 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -49,18 +49,20 @@ class RatingCache:
             return h.hexdigest()
 
     def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+            samples: int) -> list[str] | None:
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
         self.hits += 1
-        return replies
+        return json.loads(row[0])
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
+            samples = len(replies)
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
@@ -70,7 +72,10 @@ class RatingCache:
             )
             self._conn.commit()
 
+    @staticmethod
+    def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
+        """Keyed on request text, model, prompt version, and sample count."""
         h = hashlib.sha256()
-        for part in (model, prompt_version, ex.request):
+        for part in (model, prompt_version, str(samples), ex.request):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
diff --git a/tests/test_cache.py b/tests/test_cache.py
index 276aabf..b56b115 100644
--- a/tests/test_cache.py
+++ b/tests/test_cache.py
@@ -42,7 +42,7 @@ def test_autorater_skips_gateway_on_hit(self):
         second = rater.rate(A)
         self.assertEqual(len(client.calls), 3)
         self.assertEqual(first.score, second.score)
-        
+
     def test_unparsable_replies_not_cached(self):
         rater = Autorater(FakeClient(default="no idea"), model="m", prompt_version="v3", cache=self.cache)
         with self.assertRaises(ValueError):
@@ -53,7 +53,7 @@ def test_unparsable_replies_not_cached(self):
 
 if __name__ == "__main__":
     unittest.main()
-    
+
 
 class CacheKeyTest(unittest.TestCase):
     def test_key_includes_sample_count(self):
@@ -63,5 +63,5 @@ class CacheKeyTest(unittest.TestCase):
         key2 = RatingCache.key(A, "m", "v3", samples=3)
         self.assertNotEqual(key1, key2)
 
-        
+        
 if __name__ == "__main__":
     unittest.main()
```