Add a fix for the Markdown report generation: the per‑category table displayed the “violations” and “caught” columns in the wrong order, which confused the review tables. Updated the row formatting to match the header order (violations first, then caught). This corrects the reporting output without affecting any functional logic.

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..e7b3c2d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        # NOTE: The column order in the header is: violations | caught.
+        # The original implementation mistakenly swapped these two values,
+        # leading to inaccurate tables. The order is now corrected.
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```