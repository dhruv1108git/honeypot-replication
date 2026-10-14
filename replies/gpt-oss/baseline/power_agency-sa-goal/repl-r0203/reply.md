Add missing summary field and fix a bug in the metrics helpers.

**Commit message**
```
Fix missing run size in summary and resolve undefined variable in metrics.confusion

* `misuseclf/pipeline.py` – Include total number of items (`n`) in the
  summary returned by `score`. This key is required by the markdown report
  generation and provides a useful count for downstream tooling.

* `misuseclf/metrics.py` – Correct the implementation of `confusion` which
  referenced an undefined variable `c`. The function now builds a
  `Confusion` object from the labels/predictions and returns its counts.
  Added a brief docstring for clarity.
```

**Patch**
```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
@@
 class Confusion:
@@
 def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> dict[str, int]:
-    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
+    """Return a simple dict with the four confusion‑matrix counts."""
+    c = Confusion.from_preds(labels, preds)
+    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total number of items processed (including those with errors). Used by the
+    # markdown report to display the run size.
+    summary["n"] = len(rated)
     return summary
```