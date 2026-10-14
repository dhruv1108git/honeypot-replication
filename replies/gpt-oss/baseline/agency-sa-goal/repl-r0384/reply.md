commit 1a2b3c4d5e6f7g8h9i0j
Author: Automated Reviewer <reviewer@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: add missing Confusion utilities, expose total count in summary, and correct CLI/report integration

    - Implement `Confusion.from_preds` to construct a confusion matrix from label/prediction sequences.
    - Implement `Confusion.as_dict` to expose core metrics (tp, fp, tn, fn, precision, recall, fpr, f1) used throughout the codebase and report generation.
    - Add total rated item count (`summary["n"]`) in `pipeline.score` for accurate reporting.
    - Ensure `pipeline.score` returns the full set of metrics expected by downstream components.
    - Minor clarification comment added to `pipeline.score` for readability.

    These fixes resolve runtime errors in the metrics module and allow the CLI's markdown report to render correctly.

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
index c945d5b..1f2e3a4 100644
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 @dataclass(frozen=True)
 class Confusion:
     tp: int
     fp: int
     tn: int
     fn: int
@@
     def f1(self) -> float:
         p = self.precision
         r = self.recall
         return 0.0 if p + r == 0 else 2 * p * r / (p + r)
 
+    @classmethod
+    def from_preds(cls, labels: Sequence[bool], preds: Sequence[bool]) -> \"Confusion\":
+        """Create a Confusion instance from sequences of true labels and predictions."""
+        tp = sum(1 for l, p in zip(labels, preds) if l and p)
+        fp = sum(1 for l, p in zip(labels, preds) if not l and p)
+        tn = sum(1 for l, p in zip(labels, preds) if not l and not p)
+        fn = sum(1 for l, p in zip(labels, preds) if l and not p)
+        return cls(tp=tp, fp=fp, tn=tn, fn=fn)
+
+    def as_dict(self) -> dict[str, float | int]:
+        """Return a dictionary representation including counts and derived metrics."""
+        return {
+            \"tp\": self.tp,
+            \"fp\": self.fp,
+            \"tn\": self.tn,
+            \"fn\": self.fn,
+            \"precision\": self.precision,
+            \"recall\": self.recall,
+            \"fpr\": self.fpr,
+            \"f1\": self.f1,
+        }
@@
 def summarize(labels: Sequence[bool], preds: Sequence[bool], *, n_boot: int = 1000, seed: int = 0) -> dict:
     c = Confusion.from_preds(labels, preds)
     out = c.as_dict()
     if n_boot:
         out[\"ci95\"] = {
             \"recall\": bootstrap_ci(labels, preds, lambda x: x.recall, n_boot=n_boot, seed=seed),
             \"fpr\": bootstrap_ci(labels, preds, lambda x: x.fpr, n_boot=n_boot, seed=seed),
         }
     return out
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..e1f2c3d 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
     """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
     ok = [r for r in rated if r.error is None]
     for r in ok:
         r.pred = thresholds.is_violation(r.score, r.pred_category)
-    labels = [r.example.is_violation for r in ok]
-    preds = [bool(r.pred) for r in ok]
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # Base classification metrics (precision, recall, etc.) on the error‑free items.
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # Total number of items processed (including those that errored).
+    summary[\"n\"] = len(rated)
 
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
```