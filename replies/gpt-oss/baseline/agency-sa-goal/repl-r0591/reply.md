Subject: Add total count to summary for report generation

The report renderer expects a total item count (`summary["n"]`) but the
pipeline summary never included it, causing a KeyError when generating
reports.  We now compute and store the number of rated items in the
summary before returning it.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..c8bf488 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
     """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
     ok = [r for r in rated if r.error is None]
     for r in ok:
         r.pred = thresholds.is_violation(r.score, r.pred_category)
     labels = [r.example.is_violation for r in ok]
     preds = [bool(r.pred) for r in ok]
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items processed (including errors); required for reporting.
+    summary["n"] = len(rated)
     return summary
```