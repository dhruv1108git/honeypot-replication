

```diff
commit 0f3a9e2
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    fix: report table alignment and cache thread safety

    Two critical fixes:
    
    1. Fixed per-category table in report.md where "violations" and "caught"
       columns were swapped in the data compared to the headers. The metrics code
       correctly tracks violations (total true violations in category) and caught
       (correctly predicted violations), but the report was displaying them in
       reverse order. This made the weekly review metrics misleading.
    
    2. Made cache hit/miss counters thread-safe by moving increments inside
       the lock. Previously, multiple threads could increment counters concurrently,
       causing lost updates and inaccurate cache statistics. The counters are now
       updated atomically with the database operation they correspond to.
    
    These fixes ensure accurate metrics reporting and reliable cache statistics
    in concurrent execution environments.

diff --git a/misuseclf/cache.py b/misuseclf/cache.py
index 8875260..9b3c6d7 100644
--- a/misuseclf/cache.py
+++ b/misuseclf/cache.py
@@ -51,14 +51,14 @@ class RatingCache:
             h.update(b"\x00")
         return h.hexdigest()
 
     def get(self, ex: Example, model: str, prompt_version: str,
             samples: int | None = None) -> list[str] | None:
         with self._lock:
             row = self._conn.execute("SELECT replies FROM ratings WHERE key = ?",
                                      (self.key(ex, model, prompt_version),)).fetchone()
-            replies = json.loads(row[0]) if row is not None else None
-        if replies is None or (samples is not None and len(replies) != samples):  # different k: miss
+            if row is None:
+                self.misses += 1
+                return None
+            replies = json.loads(row[0])
+            if samples is not None and len(replies) != samples:  # different k: miss
+                self.misses += 1
                 return None
-        self.hits += 1
-        return replies
+            self.hits += 1
+            return replies
 
     def put(self, ex: Example, replies: list[str], *, model: str, prompt_version: str) -> None:
         with self._lock:
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..d0e7f6a 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -37,7 +37,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```