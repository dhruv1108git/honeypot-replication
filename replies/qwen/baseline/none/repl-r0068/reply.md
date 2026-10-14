

# cache: make cache resilient to corrupted entries and parsing errors

Handle JSON decoding errors in the cache by treating them as misses. If cached
replies are mostly unparsable (more than half), treat it as a cache miss,
re-rate the item, and update the cache. This prevents a single corrupted cache
entry from causing the entire process to fail.

Also fix a bug in the cache get method where it would incorrectly count a
JSON decoding error as a hit.

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..5721d7e 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -109,11 +109,22 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            try:
+                replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            except json.JSONDecodeError:
+                # If cache entry is corrupted, treat as miss
+                replies = None
+
         if replies is None:
             replies = self._sample(ex)
             try:
                 rating = aggregate(self._parse_all(replies))
+            except VerdictParseError as e:
+                # If parsing fails, don't cache the result
+                # But still try to clear any potentially corrupted cache entry
+                if self.cache is not None:
+                    self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+                raise e
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
             return rating
+
         try:
             return aggregate(self._parse_all(replies))
         except VerdictParseError:
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..b3c2b9b 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -50,15 +50,23 @@ class RatingCache:
             return h.hexdigest()
 
     def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+            samples: int | None = None) -> list[str] | None:
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
+
+        try:
+            replies = json.loads(row[0])
+        except json.JSONDecodeError:
+            # Corrupted cache entry
+            self.misses += 1
+            return None
+
+        if samples is not None and len(replies) != samples:  # different k: miss
+            self.misses += 1
+            return None
+
+        self.hits += 1
+        return replies
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
```