pipeline: add missing ratio helper, include total count in summary, fix report n‑item handling  

**Changes**
- `misuseclf/metrics.py`: introduce `_ratio` utility used by FPR‑at‑recall and per‑category calculations.
- `misuseclf/pipeline.py`: record total number of items processed (`summary["n"]`) in the scoring output.
- `misuseclf/report.py`: make the headline robust by deriving the rated count from the summary when the `n` key is absent.

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
@@
-from collections import defaultdict
+from collections import defaultdict
@@
 from typing import Callable, Sequence
 
+def _ratio(num: int, den: int) -> float:
+    """Safe division returning 0.0 when denominator is zero."""
+    return num / den if den else 0.0
+
@@
 def fpr_at_recall(scores: Sequence[float], labels: Sequence[bool], target_recall: float) -> dict:
@@
-    return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
+    return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
@@
 def per_category(categories: Sequence[str], labels: Sequence[bool], preds: Sequence[bool],
                  pred_categories: Sequence[str]) -> dict[str, dict]:
@@
-    for d in out.values():
-        d["recall"] = _ratio(d["caught"], d["violations"])
+    for d in out.values():
+        d["recall"] = _ratio(d["caught"], d["violations"])
*** End of File
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
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
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # total items processed (including errors) – useful for reports
+    summary["n"] = len(rated)
+    summary["fpr_at_recall"] = {
+        str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels, fixed_recall)
+    }
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok], labels, preds, [r.pred_category for r in ok]
+    )
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
*** End of File
diff --git a/misuseclf/report.py b/misuseclf/report.py
@@
 def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int = 20, clip: int = 200) -> str:
     lines = [
         f"# Autorater run: {summary.get('dataset', '?')}",
         "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
-        f"{summary['n']} rated · {summary['errors']} errors",
+        # Use the provided count if available; otherwise fall back to the number of items.
+        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
+        f"{summary.get('n', len(rated))} rated · {summary.get('errors', 0)} errors",
         "",
         "| metric | value | 95% CI |",
         "|---|---|---|",
*** End of File
```