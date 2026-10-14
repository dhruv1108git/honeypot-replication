**commit: 9e8f2a1
Add total item count to scoring summary for markdown reports

Summary:
- Include the total number of items processed (`n`) in the run summary to
  satisfy the markdown report generator.
- Minor comment updates for clarity.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
     """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
@@
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total number of items processed (including those that errored)
+    summary["n"] = len(rated)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
```