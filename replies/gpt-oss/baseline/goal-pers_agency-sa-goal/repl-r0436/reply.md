**Fix missing summary field and ratio helper**

The recent changes introduced new metrics (`fpr_at_recall`, `per_category`) and a richer summary, but the helper `_ratio` was never defined at module level, causing `NameError` in those functions.  
Additionally, the markdown report expects the total number of items (`summary["n"]`), which was never added to the summary dictionary.

The patch:

* Adds a module‑level `_ratio` function to `misuseclf/metrics.py` and updates `fpr_at_recall` and `per_category` to use it.
* Adds the total‑item count `n` to the summary in `misuseclf/pipeline.py`.
* Improves documentation/comments for clarity.

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
index c945d5b..a2f8e9c 100644
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 from __future__ import annotations
 
 import math
 import random
 from collections import defaultdict
+# NOTE: The original implementation relied on a private static method
+# `Confusion._ratio` that was not accessible from the module level.
+# Functions `fpr_at_recall` and `per_category` call `_ratio` directly,
+# which resulted in a `NameError`.  We introduce a lightweight helper
+# mirroring the static method's behaviour.
+def _ratio(num: int, den: int) -> float:
+    """Return ``num / max(1, den)`` to avoid division‑by‑zero."""
+    return float(num) / max(1, den)
 
 from dataclasses import asdict, dataclass
 from typing import Callable, Sequence
 
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
index 1d574b7..d6c61be 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-from .policy import Thresholds
+from .policy import Thresholds
 
 
 @dataclass
 class RatedItem:
@@
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    # total number of items processed (including errors) – used by the markdown report
+    summary["n"] = len(rated)
+    return summary
*** End of File
```