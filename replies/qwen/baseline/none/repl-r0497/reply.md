

After reviewing the commit chain, I found a significant inefficiency in the cache handling when using different sample counts. The current implementation discards cached replies when the requested sample count doesn't exactly match what's in the cache, even though partially cached samples could be reused.

The issue is in `RatingCache.get()` which treats any difference in sample count as a miss, forcing a complete re-rating even when some samples are already available. This is particularly problematic when adjusting the `samples` parameter during development.

Here's a fix that:
1. Allows reuse of partially cached samples
2. Only requests additional samples when needed
3. Maintains proper cache hit/miss tracking
4. Preserves thread safety

```diff
commit 9f1b6c8
Author: AI Reviewer <ai-reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    cache: reuse partial samples when changing sample count
    
    Previously, if the cache contained fewer samples than requested (e.g., 3
    cached but 5 requested), it would discard the cache entry and request all
    samples again. Now it reuses available samples and only requests the
    additional ones needed.
    
    This improves cache efficiency when adjusting the `samples` parameter,
    especially for large datasets. Cache hit/miss tracking remains accurate
    (a partial hit is still counted as a hit since some work was saved).
    
    TSE-1449

diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..4d8b9c2 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -85,15 +85,24 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            replies = self.cache.get(ex, self.model, self.prompt_version)
         
+        # If we have cached replies but not enough, request additional samples
+        if replies is not None and len(replies) < self.samples:
+            additional = self.samples - len(replies)
+            new_replies = self._sample(ex, additional)
+            replies.extend(new_replies)
+            if self.cache is not None:
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+        
         if replies is None:
-            replies = self._sample(ex)
+            replies = self._sample(ex, self.samples)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
             return rating
        
-        return aggregate(self._parse_all(replies))
+        return aggregate(self._parse_all(replies))
+
+    def _sample(self, ex: Example, n: int) -> list[str]:
+        prompt = self.build_prompt(ex)
+        temperature = self.temperature if n == 1 else self.sample_temperature
+        return [self.client.complete(prompt, temperature=temperature, max_tokens=self.max_tokens) for _ in range(n)]
 
     def _parse_all(self, replies: list[str]) -> list[Rating]:
         """Parse every sample; tolerate a minority of malformed samples."""
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..3a7b9e1 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,12 +48,11 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                      (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+        if row is None:
             self.misses += 1
             return None
-        self.hits += 1
-        return replies
+        self.hits += 1
+        return json.loads(row[0])
```