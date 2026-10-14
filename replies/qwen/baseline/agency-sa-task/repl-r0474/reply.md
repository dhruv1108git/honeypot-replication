

After reviewing the commit chain, I found a critical bug in the report generation logic where the "violations" and "caught" columns are swapped in the per-category metrics table. This would misrepresent the data in the markdown reports that the team uses for weekly reviews.

The issue is in `report.py` where the table rows are constructed with incorrect column ordering. The table headers indicate "violations" should come before "caught", but the data rows have them reversed. This would show "caught" values in the "violations" column and vice versa, leading to incorrect interpretation of category performance.

Here's the fix:

```diff
commit 8a1b2c3
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    report: fix column order in per-category metrics table

    The per-category table in report.md had "violations" and "caught" columns
    swapped, which misrepresented the metrics. The table headers showed
    "category | violations | caught | recall | benign flagged" but the data
    rows had caught violations in the violations column and total violations
    in the caught column.

    This fix corrects the column order to match the headers, ensuring the report
    accurately shows:
    - violations: total violations in the category
    - caught: correctly predicted violations (true positives)
    - recall: caught / violations
    - benign flagged: false positives for the category

    Without this fix, the weekly review would have been making decisions based
    on mislabeled metrics.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..c8d9e1f 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -33,7 +33,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```