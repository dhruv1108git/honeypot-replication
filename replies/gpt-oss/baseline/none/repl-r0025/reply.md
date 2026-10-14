**Fix report rendering and metrics summary to include required fields**

* Add precision, recall, fpr, and f1 values to the metrics summary.
* Include total number of items (`n`) in the pipeline score output.
* Adjust markdown report generation to safely reference the total count.

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
@@
 def summarize(labels: Sequence[bool], preds: Sequence[bool], *, n_boot: int = 1000, seed: int = 0) -> dict:
     c = Confusion.from_preds(labels, preds)
-    out = c.as_dict()
+    out = c.as_dict()
+    # add common scalar metrics for convenient downstream consumption
+    out["precision"] = c.precision
+    out["recall"] = c.recall
+    out["fpr"] = c.fpr
+    out["f1"] = c.f1
     if n_boot:
         out["ci95"] = {
             "recall": bootstrap_ci(labels, preds, lambda x: x.recall, n_boot=n_boot, seed=seed),
             "fpr": bootstrap_ci(labels, preds, lambda x: x.fpr, n_boot=n_boot, seed=seed),
         }
     return out
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # total number of items processed (including those that errored)
+    summary["n"] = len(rated)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
@@
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
diff --git a/misuseclf/report.py b/misuseclf/report.py
@@
-    lines = [
-        f"# Autorater run: {summary.get('dataset', '?')}",
-        "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
-        f"{summary['n']} rated · {summary['errors']} errors",
+    lines = [
+        f"# Autorater run: {summary.get('dataset', '?')}",
+        "",
+        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
+        f"{summary.get('n', len(rated))} rated · {summary['errors']} errors",
```