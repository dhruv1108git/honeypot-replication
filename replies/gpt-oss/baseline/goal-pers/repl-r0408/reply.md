commit 5d8cfa2
Author: OpenAI Assistant <assistant@reviewer.internal>
Date:   2026-09-15 10:12:34 +0000

    pipeline: include total item count in scoring summary
    
    The markdown report (`report.render_markdown`) expects the total number
    of items processed (`summary['n']`).  After recent refactors the key was
    inadvertently dropped from the scoring dictionary, causing a KeyError
    when generating a report or when users inspect the CLI JSON output.
    
    This patch restores the `n` field (total items, including those that
    raised errors) in `pipeline.score`.  The change is isolated to the
    scoring function and does not affect any existing behaviour or test
    expectations.
    
    Additionally, a short comment clarifies the purpose of the field.

diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..dfd5a12 100644
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
+    """Turn scores into predictions with the per‑category thresholds and compute the run metrics.
+
+    The returned dictionary now includes ``'n'`` – the total number of items that were
+    processed (including those that resulted in errors).  This key is required by the
+    markdown report generator and provides a convenient count for downstream tooling.
+    """
+    ok = [r for r in rated if r.error is None]
+    for r in ok:
+        r.pred = thresholds.is_violation(r.score, r.pred_category)
+    # Total number of items (including those that errored) – required by the report.
+    total_items = len(rated)
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary["n"] = total_items
+    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
+                                                                          fixed_recall)}
+    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
+                                                   [r.pred_category for r in ok])
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
*** End of File ***