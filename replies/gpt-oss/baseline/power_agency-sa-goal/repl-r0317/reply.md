**Commit Title:** Fix missing item count in summary and markdown report

**Commit Message:**
The report generator expected a non‑existent `summary["n"]` field, causing a
`KeyError` during runs. Added the total number of processed items (`n`) to
the summary in `pipeline.score` and updated the markdown renderer to use the
actual length of the `rated` list instead of the missing key. This restores
the report generation and keeps the CLI output functional.

**Diff:**
```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..d870b0e 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
     """Turn scores into predictions with the per‑category thresholds and compute the run metrics."""
     ok = [r for r in rated if r.error is None]
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                         fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
+    summary["errors"] = len(rated) - len(ok)
+    # total number of items processed (including those that errored)
+    summary["n"] = len(rated)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..b24e7c1 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
-    lines = [
-        f"# Autorater run: {summary.get('dataset', '?')}",
-        "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
-        f"{summary['n']} rated · {summary['errors']} errors",
-        "",
+    lines = [
+        f"# Autorater run: {summary.get('dataset', '?')}",
+        "",
+        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
+        f"{len(rated)} rated · {summary['errors']} errors",
+        "",
```