**Fix missing total item count in summary for report generation**

The markdown report expects a `n` field (total number of items) in the summary, but the `pipeline.score` function never added it. This caused a `KeyError` when rendering the report. The fix adds the `n` count to the summary before it is returned.

```diff
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items processed (including those that errored). Required by the
+    # markdown report generator which expects a `summary['n']` field.
+    summary["n"] = len(rated)
     return summary
```