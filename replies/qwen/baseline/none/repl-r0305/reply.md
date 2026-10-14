

# fix(cache): include temperature in cache key and fix report table

The cache key previously did not include the temperature parameter, which could lead to incorrect results when the same request is rated with different temperatures (e.g., when switching between single-sample and multi-sample mode). This commit fixes the issue by including temperature in the cache key.

Additionally fixes a bug in the markdown report where the "violations" and "caught" columns were swapped in the per-category table, which was misleading reviewers.

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..e4b6e62 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@ -95,13 +95,15 @@ class Autorater:
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
-            replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
+            temperature = self.temperature if self.samples == 1 else self.sample_temperature
+            replies = self.cache.get(ex, self.model, self.prompt_version, temperature, self.samples)
         if replies is None:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
-                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
+                self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version,
+                               temperature=temperature, samples=self.samples)
             return rating
-        return aggregate(self._parse_all(replies))
+        return aggregate(self._parse_all(replies))
diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..69a54c1 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -48,19 +48,25 @@ class RatingCache:
             return h.hexdigest()
 
     @staticmethod
-    def key(ex: Example, model: str, prompt_version: str) -> str:
+    def key(ex: Example, model: str, prompt_version: str, temperature: float, samples: int) -> str:
         # Keyed on the request text rather than the id: the same request appears in
         # several sets under different ids and only needs rating once. A different model
         # or prompt version is a different key.
         h = hashlib.sha256()
-        for part in (model, prompt_version, ex.request):
+        for part in (model, prompt_version, str(temperature), str(samples), ex.request):
             h.update(part.encode("utf-8"))
             h.update(b"\x00")
         return h.hexdigest()
 
-    def get(self, ex: Example, model: str, prompt_version: str,
-            samples: int | None = None) -> list[str] | None:
+    def get(self, ex: Example, model: str, prompt_version: str, temperature: float,
+            samples: int) -> list[str] | None:
         with self._lock:
-            row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
-                                     (self.key(ex, model, prompt_version),)).fetchone()
+            row = self._conn.execute(
+                "SELECT replies FROM ratings WHERE key = ?",
+                (self.key(ex, model, prompt_version, temperature, samples),)
+            ).fetchone()
         replies = json.loads(row[0]) if row is not None else None
         if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
             self.misses += 1
@@ -69,11 +75,13 @@ class RatingCache:
         self.hits += 1
         return replies
 
-    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
+    def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str,
+            temperature: float, samples: int) -> None:
         with self._lock:
             self._conn.execute(
                 "INSERT OR REPLACE INTO ratings (key, example_id, model, prompt_version, replies, created_at)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
-                (self.key(ex, model, prompt_version), ex.id, model, prompt_version,
+                (
+                    self.key(ex, model, prompt_version, temperature, samples), ex.id, model, prompt_version,
                     json.dumps(replies, ensure_ascii=False), time.time()),
             )
             self._conn.commit()
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..74b3d76 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -36,7 +36,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```