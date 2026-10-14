**Commit Title:** Fix missing utilities and add total‑item count to summary  

**Commit Message:**  
- Implement `_ratio` helper for safe division used by metrics.  
- Include total number of processed items (`n`) in pipeline scoring summary (required by markdown report).  
- Add missing imports and documentation comments.

**Diff:**  
```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
index c945d5b..e3c91a2 100644
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
-from collections import defaultdict
+from collections import defaultdict
@@
 from dataclasses import asdict, dataclass
-from typing import Callable, Sequence
+from typing import Callable, Sequence
 
 
 @dataclass(frozen=True)
@@
     return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
 
 
-def bootstrap_ci(labels: Sequence[bool], preds: Sequence[bool], metric: Callable[[Confusion], float],
+def bootstrap_ci(labels: Sequence[bool], preds: Sequence[bool], metric: Callable[[Confusion], float],
                  n_boot: int = 1000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
@@
     return vals[int((alpha / 2) * (n_boot - 1))], vals[int((1 - alpha / 2) * (n_boot - 1))]
 
+def _ratio(num: int, den: int) -> float:
+    """Safe division returning 0.0 when denominator is zero."""
+    return num / den if den else 0.0
+
 
 def fpr_at_recall(scores: Sequence[float], labels: Sequence[bool], target_recall: float) -> dict:
@@
-    return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
+    return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
 
 
 def per_category(categories: Sequence[str], labels: Sequence[bool], preds: Sequence[bool],
                  pred_categories: Sequence[str]) -> dict[str, dict]:
@@
-    for d in out.values():
-        d["recall"] = _ratio(d["caught"], d["violations"])
+    for d in out.values():
+        d["recall"] = _ratio(d["caught"], d["violations"])
     return dict(sorted(out.items()))
 
@@
-    c = Confusion.from_preds(labels, preds)
-    out = c.as_dict()
+    c = Confusion.from_preds(labels, preds)
+    out = c.as_dict()
     if n_boot:
         out["ci95"] = {
             "recall": bootstrap_ci(labels, preds, lambda x: x.recall, n_boot=n_boot, seed=seed),
@@
-    return out
+    return out
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index d870b0e..d6c61be 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-from .policy import Thresholds
+from .policy import Thresholds
 
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
+
+    # Apply per‑category thresholds to obtain binary predictions.
+    for r in ok:
+        r.pred = thresholds.is_violation(r.score, r.pred_category)
+
+    # Labels and predictions for the overall confusion matrix.
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+
+    # Core metrics (precision, recall, FPR, F1) plus optional bootstrap CIs.
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # Add the total number of items processed (including errors) – used by the markdown report.
+    summary["n"] = len(rated)
+
+    # Fixed‑recall FPR (independent of operating thresholds) and per‑category breakdown.
+    summary["fpr_at_recall"] = {
+        str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels, fixed_recall)
+    }
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok],
+        labels,
+        preds,
+        [r.pred_category for r in ok],
+    )
+
+    # Number of items that failed to rate (gateway errors, parsing errors, …).
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
*** End of File ***
```