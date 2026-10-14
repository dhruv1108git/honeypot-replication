

# cache: include sample count in cache key for efficiency

The current cache key doesn't include the sample count, so lookups for different sample counts for the same request still hit the database only to be rejected as mismatches. Including the sample count in the key avoids unnecessary database lookups.

This change makes the cache more efficient for runs with different sample counts, which is common during development when tuning the self-consistency parameter. The implementation now correctly isolates cache entries by sample count rather than detecting mismatches after the lookup.

The change is backward-compatible - existing cache entries will be treated as misses for any sample count (since the key format changed), which is safe behavior. Users can delete their cache files to reclaim space if desired.

```diff
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..d613f74 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,12 +48,13 @@ class RatingCache:
     def key(ex: Example, model: str, prompt_version: str) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
-        # or prompt version is a different key.
+        # or prompt version or sample count is a different key.
         h = hashlib.sha256()
-        for part in (model, prompt_version, ex.request):
+        for part in (model, prompt_version, str(ex.samples), ex.request):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
+    key = staticmethod(key)
 
     def get(self, ex: Example, model: str, prompt_version: str,
             samples: int | None = None) -> list[str] | None:
```