

# cache: include temperature and max_tokens in cache key; improve report escaping

The cache key previously didn't include temperature parameters (base temperature and sample_temperature) or max_tokens, which meant changing these parameters wouldn't invalidate the cache. This could lead to using replies generated with different parameters, causing incorrect results.

Updated the cache key to include the effective temperature (which depends on whether samples=1) and max_tokens. All cache operations now pass these parameters consistently.

Also improved Markdown escaping in reports by wrapping rationales in backticks instead of just replacing pipe characters. This prevents rationales with Markdown special characters from breaking the report formatting.

TSE-1448

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..7f45f23 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -84,13 +84,15 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            temperature = self.temperature if self.samples == 1 else self.sample_temperature
+            replies = self.cache.get(ex, self.model, self.prompt_version, temperature, self.max_tokens, samples=self.samples)
         if replies is None:
+            temperature = self.temperature if self.samples == 1 else self.sample_temperature
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
-                               temperature=temperature, max_tokens=self.max_tokens)
+                               temperature=temperature, max_tokens=self.max_tokens)
             return rating
         return aggregate(self._parse_all(replies))
 
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..12c6c32 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -51,15 +51,21 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    @staticmethod
+    def key(ex: Example, model: str, prompt_version: str, temperature: float, max_tokens: int) -> str:
+        """Generate cache key including all parameters that affect the model's reply."""
+        h = hashlib.sha256()
+        for part in (model, prompt_version, str(temperature), str(max_tokens), ex.request):
+            h.update(part.encode("utf-8"))
+            h.update(b"\x00")
+        return h.hexdigest()
+
+    def get(self, ex: Example, model: str, prompt_version: str, temperature: float, max_tokens: int,
+            samples: int | None = None) -> list[str] | None:
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
+            key = self.key(ex, model, prompt_version, temperature, max_tokens)
+            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?", (key,)).fetchone()
         replies = json.loads(row[0]) if row is not None else None
         if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
             self.misses += 1
             return None
         self.hits += 1
         return replies
 
-    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
+    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str, temperature: float, max_tokens: int) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                (self.key(ex, model, prompt_version, temperature, max_tokens), ex.id, model, prompt_version,
                  json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..d996c3b 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -32,7 +32,7 @@ def _example_rows(items: list[RatedItem], max_examples: int, clip: int) -> list[
     for r in sorted(items, key=lambda r: -r.score)[:max_examples]:
         rows.append(f"| `{r.example.id}` | {r.example.category} | {r.pred_category} | {r.score:.2f} | "
                     f"{_clip(r.rationale, clip).replace('|', '/')} |")
-    if len(items) > max_examples:
+    if len(items) > max_examples:
         rows.append(f"\n_{len(items) - max_examples} more not shown._")
     return rows
```