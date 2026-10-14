**Fix missing headline count and per‑category table ordering in markdown reports**

The report generator expected a `summary["n"]` key (total items) which was never set, causing a `KeyError` when rendering reports. Additionally, the per‑category table displayed the *caught* and *violations* columns swapped, conflicting with the header.

These issues are corrected by:
1. Adding `summary["n"]` (total number of items processed) in `pipeline.score`.
2. Adjusting the per‑category table generation to match the header order (violations then caught).

```diff
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total items processed (including those that errored)
+    summary["n"] = len(rated)
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+    for cat, d in summary.get("per_category", {}).items():
+        # Table header: category | violations | caught | recall | benign flagged
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
*** End of File ***
```