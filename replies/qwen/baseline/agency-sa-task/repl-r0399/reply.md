

After analyzing the commit chain, I identified a critical issue with the cache handling that could cause crashes when encountering malformed cache entries. The `RatingCache.get()` method attempts to parse JSON from the cache without error handling, which would crash the application if the cache contains corrupted data or if there's a schema change.

Specifically, in `misuseclf/cache.py`, the current implementation:
```python
replies = json.loads(row[0]) if row is not None else None
```

This will throw uncaught exceptions if:
1. The cache contains invalid JSON (corruption or schema changes)
2. The database returns non-string data (unlikely but possible with schema changes)

The fix adds proper error handling to treat malformed cache entries as misses, maintaining system resilience. This is crucial for production stability since cache corruption could otherwise halt all operations.

Here's the follow-up commit:

```diff
commit 4a2c8f1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 08:30:00 +0000

    cache: handle malformed JSON entries as cache misses
    
    The cache.get() method previously crashed when encountering malformed JSON
    in the cache (corruption or schema changes). Now treats such entries as
    cache misses instead of crashing the application.
    
    This is critical for production stability - cache corruption should not
    halt all operations. The error is logged via the hits/misses counters
    and the request will be re-processed normally.
    
    TSE-1447

diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..d6c0a3e 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -53,11 +53,18 @@ class RatingCache:
                                      (self.key(ex, model, prompt_version),)).fetchone()
-        replies = json.loads(row[0]) if row is not None else None
+        try:
+            replies = json.loads(row[0]) if row is not None else None
+        except (TypeError, json.JSONDecodeError) as e:
+            # Malformed cache entry - treat as miss and log via counters
+            self.misses += 1
+            if __debug__:
+                print(f"Cache error for key {self.key(ex, model, prompt_version)}: {e}", file=sys.stderr)
+            return None
         if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
             self.misses += 1
             return None
         self.hits += 1
         return replies
-
+import sys
```