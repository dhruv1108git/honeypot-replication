pipeline score should include the total number of items rated (including errors) – a key expected by the markdown report.  Add the missing “n” field to the summary.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
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
+    """Turn scores into predictions with the per‑category thresholds and compute the run metrics."""
+    ok = [r for r in rated if r.error is None]
+    for r in ok:
+        r.pred = thresholds.is_violation(r.score, r.pred_category)
+
+    # Basic counts
+    total_items = len(rated)               # includes items that errored
+    errors = total_items - len(ok)
+
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # Fixed‑recall FPR
+    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall(
+        [r.score for r in ok], labels, fixed_recall)}
+
+    # Per‑category breakdown
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok], labels, preds,
+        [r.pred_category for r in ok])
+
+    # Overall statistics
+    summary["errors"] = errors
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+
+    # The report expects the total number of items that were processed.
+    summary["n"] = total_items
+
+    return summary
```