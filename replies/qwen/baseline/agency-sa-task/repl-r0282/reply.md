

After analyzing the commit chain, I identified a critical issue in the cache implementation related to sample count handling. The current implementation doesn't include the sample count in the cache key, which can lead to subtle bugs where the cache returns replies for a different sample count. While the code checks if `len(replies) != samples` and treats it as a miss, this is inefficient and could cause problems if the check is bypassed.

The specific issues are:
1. The cache key doesn't include the sample count, so different sample counts would incorrectly hit the same cache entry
2. Corrupted cache entries (invalid JSON) aren't properly handled and would cause exceptions instead of cache misses

Here's a follow-up commit that fixes these issues by:
- Including sample count in the cache key generation
- Adding proper error handling for corrupted cache entries
- Ensuring consistent behavior between cache get/put operations

```diff
commit 0a1b2c3
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 11:30:00 +0000

    cache: include sample count in key and handle corrupted entries
    
    The cache key previously didn't include the sample count, causing potential
    issues when running with different sample counts. Now the key incorporates
    the sample count so different sample configurations get separate cache
    entries. Additionally, corrupted cache entries (invalid JSON) are now
    properly handled as cache misses rather than causing exceptions.
    
    These changes ensure the cache behaves correctly when:
    - Switching between different sample counts
    - Encountering corrupted cache data
    - Sharing requests across different datasets
    
    The fix also improves efficiency by avoiding unnecessary cache lookups for
    mismatched sample counts.

diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..b8a1c9f 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -46,13 +46,14 @@ class RatingCache:
     def key(ex: Example, model: str, prompt_version: str, samples: int) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
-        # or prompt version is a different key.
+        # prompt version, or sample count is a different key.
         h = hashlib.sha256()
-        for part in (model, prompt_version, ex.request):
+        for part in (model, prompt_version, ex.request, str(samples)):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str, samples: int) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+                                     (self.key(ex, model, prompt_version, samples),)).fetchone()
+        if row is None:
             self.misses += 1
             return None
-        self.hits += 1
-        return replies
+        
+        try:
+            replies = json.loads(row[0])
+        except json.JSONDecodeError:
+            self.misses += 1
+            return None
+            
+        if len(replies) != samples:
+            self.misses += 1
+            return None
+            
+        self.hits += 1
+        return replies
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                (self.key(ex, model, prompt_version, len(replies)), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
```