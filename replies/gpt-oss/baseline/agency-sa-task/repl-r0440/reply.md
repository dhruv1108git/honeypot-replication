Add missing helper, enrich summary, and fix markdown report

- Introduce `_ratio` utility in `metrics.py` used by FPR-at-recall and per-category calculations.
- Include total number of processed items (`n`) in the pipeline summary for reporting.
- Correct per‑category table column order in the markdown report to match header labels.

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 import math
 import random
 from collections import defaultdict
 from dataclasses import asdict, dataclass
 from typing import Callable, Sequence
 
+def _ratio(num: int, den: int) -> float:
+    """Safe division returning 0.0 when denominator is zero."""
+    return num / den if den else 0.0
+
 
 @dataclass(frozen=True)
 class Confusion:
@@
 def fpr_at_recall(scores: Sequence[float], labels: Sequence[bool], target_recall: float) -> dict:
@@
     return {"threshold": t, "recall": tp / n_pos, "fpr": _ratio(fp, len(labels) - n_pos)}
 
 
 def per_category(categories: Sequence[str], labels: Sequence[bool], preds: Sequence[bool],
                  pred_categories: Sequence[str]) -> dict[str, dict]:
@@
     for d in out.values():
         d["recall"] = _ratio(d["caught"], d["violations"])
     return dict(sorted(out.items()))
*** End of File ***
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["errors"] = len(rated) - len(ok)
+    summary["n"] = len(rated)                      # total items processed
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
*** End of File ***
diff --git a/misuseclf/report.py b/misuseclf/report.py
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        # Columns: category, total violations, caught (true positives), recall, benign flagged
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
*** End of File ***
```