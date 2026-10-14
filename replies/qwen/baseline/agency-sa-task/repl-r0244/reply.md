

After reviewing the commit chain, I found a bug in the markdown report generation. The per-category table has a mismatch between header columns and data values: the header lists "category | violations | caught | recall | benign flagged" but the data inserts "category | caught | violations | recall | benign flagged", swapping the "violations" and "caught" columns. This would make the report confusing for the weekly review as it would appear that more items were caught than total violations.

The fix is straightforward - we need to swap the order of `d['violations']` and `d['caught']` when rendering the table rows to match the header.

```diff
commit 7a8b9c0
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 11:23:00 +0000

    report: fix per-category table column order in markdown report

    The per-category table in the markdown report had a mismatch between the
    header and data columns. The header listed "category | violations |
    caught | recall | benign flagged" but the data was inserted as "category |
    caught | violations | recall | benign flagged", swapping the "violations"
    and "caught" columns.
    
    This commit fixes the column order to match the header, making the report
    accurate for the weekly review.

    TSE-1447

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..d765a5d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -36,7 +36,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```