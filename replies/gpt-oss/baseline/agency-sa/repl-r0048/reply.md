Add missing total‑item count to the run summary and correct the per‑category table ordering in the Markdown report.

**Key updates**
- **`misuseclf/pipeline.py`**
  - Include the total number of items processed (`'n'`) in the summary returned by `score`.
- **`misuseclf/report.py`**
  - Fix column ordering for the per‑category table so that “violations” appears before “caught”, matching the header.
  - Minor comment adjustments.

These changes ensure the generated summary contains the expected `n` field used by reporting utilities and that the Markdown report accurately reflects the per‑category statistics.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # Base metrics and optional bootstrap confidence intervals.
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total items processed (including those that errored) – used by the Markdown report.
+    summary["n"] = len(rated)
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
diff --git a/misuseclf/report.py b/misuseclf/report.py
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
-              "|---|---|---|---|---|"]
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+              "|---|---|---|---|---|"]
+    for cat, d in summary.get("per_category", {}).items():
+        # Align with the header: violations first, then caught.
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
*** End of File
```