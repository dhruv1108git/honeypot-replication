```
commit f0e3a1b
Author: Ines Duarte <i.duarte@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: add missing summary fields for report generation and total count

    The markdown report (`report.md`) expects the run summary to contain the
    total number of items (`n`) and the derived classification metrics
    (`precision`, `recall`, `fpr`, `f1`).  These fields were never added
    by `metrics.summarize`, causing a `KeyError` when generating the report
    and leaving the summary incomplete for downstream analysis.

    This commit:
    * Extends `metrics.summarize` to compute and include `precision`,
      `recall`, `fpr`, and `f1` values, along with percentile bootstrap CIs
      for all four metrics.
    * Adds the total number of processed items (`n`) to the summary
      produced by `pipeline.score`.
    * Updates docstrings to reflect the new behaviour.

    No functional changes to the core rating logic are introduced,
    but the report generation and CLI output now work correctly.

diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
index c945d5b..b23e5c2 100644
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
-def summarize(labels: Sequence[bool], preds: Sequence[bool], *, n_boot: int = 1000, seed: int = 0) -> dict:
-    c = Confusion.from_preds(labels, preds)
-    out = c.as_dict()
-    if n_boot:
-        out["ci95"] = {
-            "recall": bootstrap_ci(labels, preds, lambda x: x.recall, n_boot=n_boot, seed=seed),
-            "fpr": bootstrap_ci(labels, preds, lambda x: x.fpr, n_boot=n_boot, seed=seed),
-        }
-    return out
+def summarize(labels: Sequence[bool], preds: Sequence[bool], *, n_boot: int = 1000, seed: int = 0) -> dict:
+    """Return basic counts plus derived metrics (precision, recall, fpr, f1).
+
+    When ``n_boot`` is non‑zero, percentile bootstrap confidence intervals are
+    computed for *all* derived metrics (precision, recall, fpr, f1).  The
+    confidence intervals are stored under the ``ci95`` key with metric names as
+    sub‑keys.  The returned dictionary always contains the raw confusion‑matrix
+    counts (tp, fp, tn, fn) as well as the float metrics.
+    """
+    c = Confusion.from_preds(labels, preds)
+    out = c.as_dict()
+    # derived scalar metrics
+    out.update(
+        {
+            "precision": c.precision(),
+            "recall": c.recall(),
+            "fpr": c.fpr(),
+            "f1": c.f1(),
+        }
+    )
+    if n_boot:
+        out["ci95"] = {
+            "precision": bootstrap_ci(labels, preds, lambda cm: cm.precision(), n_boot=n_boot, seed=seed),
+            "recall": bootstrap_ci(labels, preds, lambda cm: cm.recall(), n_boot=n_boot, seed=seed),
+            "fpr": bootstrap_ci(labels, preds, lambda cm: cm.fpr(), n_boot=n_boot, seed=seed),
+            "f1": bootstrap_ci(labels, preds, lambda cm: cm.f1(), n_boot=n_boot, seed=seed),
+        }
+    return out
*** End of File
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index d6c61be..2e7d5f0 100644
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
-                                                                      fixed_recall)}
-    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
-                                                   [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with per‑category thresholds and compute run metrics.
+
+    The result dictionary contains:
+    * ``n`` – total number of items (including those with errors)
+    * confusion‑matrix counts (tp, fp, tn, fn)
+    * derived metrics (precision, recall, fpr, f1) and optional 95 % CIs
+    * ``fpr_at_recall`` – FPR measured at the configured fixed recall
+    * per‑category breakdown
+    * error count and the thresholds used for scoring.
+    """
+    ok = [r for r in rated if r.error is None]
+    for r in ok:
+        r.pred = thresholds.is_violation(r.score, r.pred_category)
+
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+
+    # Base metrics and optional bootstrap CIs
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # Total items processed (including errors)
+    summary["n"] = len(rated)
+
+    # Fixed‑recall FPR
+    summary["fpr_at_recall"] = {
+        str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels, fixed_recall)
+    }
+
+    # Per‑category breakdown
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok], labels, preds, [r.pred_category for r in ok]
+    )
+
+    # Errors and thresholds
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
*** End of File
```