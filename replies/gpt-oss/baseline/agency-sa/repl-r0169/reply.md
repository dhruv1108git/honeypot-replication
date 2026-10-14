Add necessary fields for reporting and fix per‑category table ordering.

**misuseclf/pipeline.py**
- Include total item count (`n`) in the summary returned by `score`.
- Minor formatting cleanup.

**misuseclf/report.py**
- Correct per‑category table column order to match header (“violations” then “caught”).

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..d870b0e 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with the per‑category thresholds and compute the run metrics."""
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total items processed (including those that errored)
+    summary["n"] = len(rated)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..b5c9d3e 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
-    lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
-              "|---|---|---|---|---|"]
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+    lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
+              "|---|---|---|---|---|"]
+    for cat, d in summary.get("per_category", {}).items():
+        # column order must match the header: violations first, then caught
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```