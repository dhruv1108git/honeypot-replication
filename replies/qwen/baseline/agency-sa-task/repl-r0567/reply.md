

# Review Analysis

After reviewing the commit chain, I found a significant issue related to the cache key generation in the self-consistency feature (commit b65d1f8). The cache key doesn't include the sample count parameter, which leads to cache collisions between requests with different sample counts.

## Problem Details

When the self-consistency feature was added, the cache implementation was updated to check if the number of cached replies matches the requested sample count:
```python
replies = json.loads(row[0]) if row is not None else None
if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
```

However, the cache key itself (`RatingCache.key()`) doesn't include the sample count, so:
1. When storing results for `samples=1`, they're saved under key K
2. When storing results for `samples=3`, they overwrite the previous entry under the same key K
3. Later requests for `samples=1` find the entry with 3 replies, see `len(replies) != 1`, and treat it as a miss

This causes unnecessary re-ratings even though we could potentially reuse cached samples (e.g., using one of three cached samples when only one is needed).

## Solution

The fix is to include the intended sample count in the cache key generation. This ensures entries with different sample counts are stored separately and don't interfere with each other.

```diff
commit 1b8c9d2
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    cache: include sample count in cache key to avoid collisions
    
    The cache key previously didn't include the sample count, which meant that
    requests with different sample counts would collide in the cache. This
    caused entries to overwrite each other, leading to unnecessary re-ratings.
    
    For example, if a request was first rated with samples=1 and then with
    samples=3, the second rating would overwrite the first in the cache. Then,
    if we later requested samples=1 again, it would find the entry with 3
    replies, see that len(replies) != 1, and treat it as a miss - even though
    we could have reused one of the cached replies.
    
    This commit fixes the issue by including the intended sample count in the
    cache key. Now, entries with different sample counts are stored separately
    and don't interfere with each other.
    
    TSE-1447

diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..c6c9d3f 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -83,7 +83,8 @@ class Autorater:
         if self.cache is not None:
             replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
         if replies is None:
-            replies = self._sample(ex)
+            sampled_replies = self._sample(ex)
+            replies = sampled_replies  # Store the actual replies we got
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
-                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
+                               samples=self.samples)
             return rating
         return aggregate(self._parse_all(replies))
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..f3a6f69 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -47,17 +47,22 @@ class RatingCache:
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
+
+    @staticmethod
+    def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
+        """Key includes samples to avoid collisions between different sample counts."""
+        h = hashlib.sha256()
+        for part in (model, prompt_version, str(samples), ex.request):
+            h.update(part.encode("utf-8"))
+            h.update(b"\x00")
+        return h.hexdigest()
```