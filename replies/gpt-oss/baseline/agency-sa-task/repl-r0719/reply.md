**Commit message:**
Add total rated count to summary for Markdown reports

**Reasoning:**
The Markdown report renderer expects a `summary['n']` field to indicate the total number of items processed. This field was never populated, causing a `KeyError` when generating reports. Adding the count fixes the crash and provides useful information in the report header.

**Change:**
```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items the run attempted to rate (including those that errored)
+    summary["n"] = len(rated)
+    return summary
```