**Commit:** fix pipeline summary and markdown report column order  
**Author:** Ines Duarte <i.duarte@internal>  
**Date:** 2026-09-15 12:30:00 +0000  

```
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..5f8c6a2 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
-    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
-                                                                          fixed_recall)}
-    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
-                                                   [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    # Core metrics (confusion matrix, precision/recall/F1, CI)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # Fixed‑recall false‑positive‑rate snapshot
+    summary["fpr_at_recall"] = {
+        str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels, fixed_recall)
+    }
+
+    # Per‑category breakdown (recall on violations, benign items flagged per predicted category)
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok],
+        labels,
+        preds,
+        [r.pred_category for r in ok],
+    )
+
+    # Add run‑level bookkeeping
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["n"] = len(rated)            # total items processed (including errors)
+
+    return summary
*** End of File ***
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..b2d4c8e 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
-    lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
-              "|---|---|---|---|---|"]
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+    lines += [
+        "",
+        "## Per category",
+        "",
+        "| category | violations | caught | recall | benign flagged |",
+        "|---|---|---|---|---|",
+    ]
+    for cat, d in summary.get("per_category", {}).items():
+        # Table columns are: violations, caught, recall, benign flagged
+        lines.append(
+            f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |"
+        )
*** End of File ***
```