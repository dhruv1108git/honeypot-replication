**Commit Title:** Fix missing ratio helper and add total item count to summary

**Commit Message:**
- Add safe division helper `_ratio` to `metrics.py` (required by Confusion calculations and other metric functions).
- Include total number of processed items (`n`) in the scoring summary within `pipeline.py`.
- Minor documentation update in `metrics.py` to clarify the purpose of `_ratio`.

**Diff:**
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
+
+
+def _ratio(num: int | float, denom: int | float) -> float:
+    """Safe division returning ``0.0`` when ``denom`` is zero.
+
+    Used throughout the metric calculations to avoid ``ZeroDivisionError``
+    when there are no positive or negative examples.
+    """
+    return float(num) / float(denom) if denom else 0.0
 
 
 @dataclass(frozen=True)
 class Confusion:
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
+    # total number of items processed (including those with errors)
+    summary["n"] = len(rated)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
```