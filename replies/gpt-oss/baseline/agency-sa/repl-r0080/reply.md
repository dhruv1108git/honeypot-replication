fix: add total rated count “n” to pipeline summary for report generation

The markdown report generator (`misuseclf.report`) expects the summary dict to contain an `n` field representing the total number of items processed. This field was missing after recent refactors, causing a KeyError when generating reports.  
We now populate `summary["n"]` in `pipeline.score` with the total count of rated items (including any errors). This addition is backwards‑compatible and does not affect existing metrics or CLI behavior.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..d870b0e 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # Include the total number of items processed (including those with errors)
+    # This field is required by the markdown report renderer.
+    summary["n"] = len(rated)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
```