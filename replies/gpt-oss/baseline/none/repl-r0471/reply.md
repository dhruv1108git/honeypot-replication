**commit: fix-metrics-and-summary**

*Add a safe global ratio helper and total‑item count to scoring.*

- Define a module‑level `_ratio` function in `misuseclf/metrics.py` to avoid `NameError` when computing FPR at fixed recall and per‑category recall.
- Use this helper (via existing references) for ratio calculations.
- Include the total number of items processed (`summary["n"]`) in `misuseclf/pipeline.py` score output, required by the markdown report.

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
@@
-from __future__ import annotations
-
-import math
-import random
-from collections import defaultdict
-from dataclasses import asdict, dataclass
-from typing import Callable, Sequence
+from __future__ import annotations
+
+import math
+import random
+from collections import defaultdict
+from dataclasses import asdict, dataclass
+from typing import Callable, Sequence
@@
 class Confusion(frozen=True):
@@
     @staticmethod
     def _ratio(a: int, b: int) -> float:
         return a / b if b != 0 else 0.0  # handle division by zero inside metric methods
+
+
+def _ratio(a: int, b: int) -> float:
+    """Return a / b, or 0 when denominator is zero."""
+    return a / b if b != 0 else 0.0
@@
 def fpr_at_recall(scores: Sequence[float], labels: Sequence[bool], target_recall: float) -> dict:
@@
-    return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
+    return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
@@
 def per_category(categories: Sequence[str], labels: Sequence[bool], preds: Sequence[bool],
                  pred_categories: Sequence[str]) -> dict[str, dict]:
@@
-    for d in out.values():
-        d["recall"] = _ratio(d["caught"], d["violations"])
+    for d in out.values():
+        d["recall"] = _ratio(d["caught"], d["violations"])
     return dict(sorted(out.items()))
*** End of File
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # total number of items processed (including those that errored)
+    summary["n"] = len(rated)
@@
-    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
-                                                   [r.pred_category for r in ok])
+    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
+                                                   [r.pred_category for r in ok])
*** End of File
```