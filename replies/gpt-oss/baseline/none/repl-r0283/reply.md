Add total item count to run summary
This restores the `n` field that the markdown report expects.
Without it the report generation crashes with a KeyError when
displaying the headline “X rated”.  The field is simply the total
number of items (including those that errored) and does not affect
any existing metrics.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..d870b0e 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
-    ok = [r for r in rated if r.error is None]
-    for r in ok:
-        r.pred = thresholds.is_violation(r.score, r.pred_category)
-    labels = [r.example.is_violation for r in ok]
-    preds = [bool(r.pred) for r in ok]
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
-    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
-                                                                          fixed_recall)}
-    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
-                                                   [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+    ok = [r for r in rated if r.error is None]
+    for r in ok:
+        r.pred = thresholds.is_violation(r.score, r.pred_category)
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # total number of items processed (including those that errored)
+    summary["n"] = len(rated)
+
+    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
+                                                                          fixed_recall)}
+    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
+                                                   [r.pred_category for r in ok])
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
```