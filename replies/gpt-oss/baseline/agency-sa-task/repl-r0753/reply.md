pipeline‑score‑n‑field

Add the total number of items processed (`n`) to the score summary.  
The markdown report expects this key, and including it makes the CLI output
complete and avoids a KeyError when rendering the report.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    # total number of items (including those that errored)
+    summary["n"] = len(rated)
+    return summary
```