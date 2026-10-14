pipeline‑score: add total count and fix Autorater cache bug

- Fixed a NameError in `Autorater.rate` where `_parse_all` was called without `self`.
- Added the total number of processed items (`n`) to the scoring summary, which is required by the Markdown report.
- Updated the comment to reflect the purpose of the changes.

```
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
@@
         if replies is None:
             replies = self._sample(ex)
             rating = aggregate(self._parse_all(replies))  # only usable reply sets are cached
             if self.cache is not None:
                 self.cache.put(ex, replies, model=self.model, prompt_version=self.prompt_version)
             return rating
-        return aggregate(_parse_all(replies))
+        # Cached replies are already available; parse and aggregate them.
+        return aggregate(self._parse_all(replies))
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
+    # Base classification metrics, optionally with bootstrap confidence intervals.
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # Total number of items processed (including those with errors) – required by the report.
+    summary["n"] = len(rated)
+    # FPR at a fixed recall, independent of the operating thresholds.
+    summary["fpr_at_recall"] = {
+        str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels, fixed_recall)
+    }
+    # Per‑category breakdown of violations caught and benign items flagged.
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok],
+        labels,
+        preds,
+        [r.pred_category for r in ok],
+    )
+    # Number of items that failed to be rated (gateway errors, parsing errors, etc.).
+    summary["errors"] = len(rated) - len(ok)
+    # The thresholds actually used for this run.
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
```