pipeline‑score‑add‑total‑count‑and‑fix‑report‑column‑order

Added a total item count (`n`) to the scoring summary so the markdown report can display the number of items processed. Fixed the per‑category table in the markdown report to correctly show “violations” then “caught” columns (they were previously swapped).

```diff
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total number of items processed (including errors) – used by the markdown report
+    summary["n"] = len(rated)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
```

```diff
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+    for cat, d in summary.get("per_category", {}).items():
+        # correct column order: violations first, then caught
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```