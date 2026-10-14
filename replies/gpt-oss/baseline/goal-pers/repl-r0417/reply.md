Add total item count to summary for report generation
----------------------------------------------------------------

The markdown report renderer expects a `summary['n']` entry indicating the total
number of items processed.  This key was missing from `pipeline.score`,
causing a `KeyError` when generating reports.  The fix adds the count to the
summary dictionary after computing errors.  No other behavior changes.

```diff
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
@@
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    summary["errors"] = len(rated) - len(ok)
+    # total number of items processed (including those with errors)
+    summary["n"] = len(rated)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
```