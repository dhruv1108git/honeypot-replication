Fix CLI metrics config handling, add total‑count for reports, and correct metrics helper

- Misuseclf CLI attempted to read metric overrides (`fixed_recall`, `bootstrap_samples`) from an undefined variable `mc`, causing a NameError.
- Reports expect a total‑item count (`summary["n"]`) but the pipeline never populated it, leading to a KeyError during markdown rendering.
- The `confusion` helper in `metrics.py` referenced an undefined variable `c`, breaking the function.

Implemented fixes:
* In `misuseclf/cli.py` read the optional `[metrics]` section into `mc` before using it.
* In `misuseclf/pipeline.py` add `summary["n"] = len(rated)` to expose the total number of processed items for reporting.
* In `misuseclf/metrics.py` correctly compute the confusion matrix inside `confusion`.
* Added explanatory comments for the new logic.

These changes restore CLI functionality, enable markdown reports, and make the metrics utilities reliable.

```diff
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index 81cd2ad..c3387ee 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@
     rated = pipeline.rate(rater, examples, workers=workers)
-    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
-                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
+    # Load optional metrics configuration (fixed recall and bootstrap sample count)
+    mc = cfg.get("metrics", {})
+    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
+                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
     if rater.cache is not None:
         summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
     summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                     "dataset": dataset})
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..d870b0e 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    # Total number of items processed (including those that errored). This is used by the markdown report.
+    summary["n"] = len(rated)
+    return summary
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
index c945d5b..04e534d 100644
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 
-def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> dict[str, int]:
-    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
+def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> dict[str, int]:
+    """Return a simple TP/FP/TN/FN dict for legacy callers."""
+    c = Confusion.from_preds(labels, preds)
+    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
```