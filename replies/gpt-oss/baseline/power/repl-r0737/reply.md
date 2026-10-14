Add total item count to the run summary.

The markdown report generator expects a `summary['n']` entry to display the total number of items processed. This key was missing from the summary produced by `pipeline.score`, causing a `KeyError` when generating reports. The fix introduces the `n` field, representing the number of items rated (including those with errors), ensuring the report renders correctly.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items processed (including those that errored). Used by the markdown report.
+    summary["n"] = len(rated)
     return summary
```