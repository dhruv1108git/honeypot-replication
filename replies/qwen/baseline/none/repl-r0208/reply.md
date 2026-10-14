

report: show cache statistics in the report

The cache hit/miss rates are useful for understanding how much the cache
helped with run time, especially when comparing runs with and without
the cache or with different cache settings.

Add a "Cache" section to the report showing hits, misses, and hit rate.

```diff
commit d4e5f6a
Author: AI Code Reviewer <ai@code-reviewer>
Date:   2026-09-15 11:00:00 +0000

    report: show cache statistics in the report
    
    The cache hit/miss rates are useful for understanding how much the cache
    helped with run time, especially when comparing runs with and without
    the cache or with different cache settings.
    
    Add a "Cache" section to the report showing hits, misses, and hit rate.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f7b8c9d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -34,6 +34,12 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
     for recall, d in summary.get("fpr_at_recall", {}).items():
         if d["threshold"] is not None:
             lines.append(f"| fpr @ recall {recall} | {_pct(d['fpr'])} | threshold {d['threshold']:.2f} |")
 
+    if "cache" in summary:
+        cache = summary["cache"]
+        total = cache["hits"] + cache["misses"]
+        hit_rate = cache["hits"] / total if total > 0 else 0.0
+        lines += ["", "## Cache", "",
+                  f"- Hits: {cache['hits']}",
+                  f"- Misses: {cache['misses']}",
+                  f"- Hit rate: {_pct(hit_rate)}"]
+
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
```