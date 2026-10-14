Commit: Add total item count (“n”) to summary for report rendering

This fixes a KeyError in the markdown report generation where the
summary dictionary was expected to contain the total number of items
rated (`summary["n"]`).  The count is now added in `pipeline.score`,
allowing reports to be generated correctly and preserving the
original behavior for all other consumers of the summary.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                        fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
+    # total number of items processed (including errors); used by the markdown report
+    summary["n"] = len(rated)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
```