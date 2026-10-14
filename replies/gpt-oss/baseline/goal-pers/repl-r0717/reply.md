pipeline score: include total item count for reports

The markdown report expects a field `summary['n']` to display the total number of
items processed.  Previously the scoring summary omitted this information,
causing a `KeyError` when generating `report.md`.  Add the missing field and
update the docstring to clarify its purpose.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with the per-category thresholds and compute the run metrics.
+
+    The returned summary now includes the total number of items processed under the key ``'n'``.
+    This is needed by the markdown report generator.
+    """
@@
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    summary["errors"] = len(rated) - len(ok)
+    # total number of items (including errors) – required for report generation
+    summary["n"] = len(rated)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
```