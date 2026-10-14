**Commit: Add missing imports and expose total item count in summary**

*Fixes NameError for `Example` and `CATEGORIES` in `autorater.py` after recent refactor.  
*Adds the total number of processed items (`n`) to the scoring summary, enabling the markdown report to display the correct count.*

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
@@
 from . import prompts
 from .cache import RatingCache
+from .data import Example
+from .policy import CATEGORIES
@@
 class VerdictParseError(ValueError):
@@
 class Autorater:
@@
     def rate(self, ex: Example) -> Rating:
         replies = None
         if self.cache is not None:
             replies = self.cache.get(ex, self.model, self.prompt_version, samples=self.samples)
         if replies is None:
@@
         return aggregate(self._parse_all(replies))
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
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # Total number of items processed (including those that errored).
+    summary["n"] = len(rated)
+
+    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall(
+        [r.score for r in ok], labels, fixed_recall)}
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok], labels, preds, [r.pred_category for r in ok])
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
```