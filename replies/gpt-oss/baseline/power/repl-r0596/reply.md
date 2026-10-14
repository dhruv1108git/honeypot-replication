**Fix missing total-item count in summary**

The markdown report expects a `summary['n']` field (total number of items processed), but the pipeline summary did not include it. This caused a `KeyError` when generating reports.

Added the `n` field to the summary returned by `pipeline.score`, representing the total number of rated items (including those that errored). This restores compatibility with the report generation and improves the overall completeness of the summary data.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items processed (including those that errored). Used by the
+    # markdown report for the headline metrics.
+    summary["n"] = len(rated)
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
```