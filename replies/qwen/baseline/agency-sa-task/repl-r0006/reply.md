

After analyzing the commit chain, I identified a critical bug in the report generation code. The per-category metrics table in the markdown report has a column ordering mismatch between headers and data. The headers correctly list "violations | caught" but the data is output as "caught | violations", making the report confusing and potentially misleading for review.

The issue is in `report.py` where the per-category table rows are generated. The data dictionary from `metrics.per_category()` contains:
- `violations`: total violations in the category
- `caught`: correctly caught violations in the category

But the report was displaying them in reverse order, showing caught items as total violations and vice versa.

Here's the follow-up commit that fixes this issue:

```diff
commit 1a2b3c4
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 11:23:01 +0000

    report: fix per-category table column ordering
    
    The per-category table in report.md had a critical mismatch between column
    headers and data. The headers correctly listed "violations | caught" but
    the data was output as "caught | violations", making the report confusing
    and potentially misleading for the weekly review.
    
    This bug could cause misinterpretation of model performance, particularly
    when analyzing which categories have the most violations versus which are
    being correctly caught. The fix swaps the order of d['violations'] and
    d['caught'] to match the column headers.
    
    TSE-1447

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..f3d4a5b 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -35,7 +35,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```