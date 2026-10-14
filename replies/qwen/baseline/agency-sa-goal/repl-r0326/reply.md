

After reviewing the entire commit chain, I've identified a critical bug in the markdown report generation. The per-category table in `report.py` incorrectly swaps the "violations" and "caught" columns, which would misrepresent data in the weekly review reports.

In commit 9e03a6c, the markdown headers correctly specify:
`| category | violations | caught | recall | benign flagged |`

But the data rows incorrectly place "caught" before "violations":
```python
f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |"
```

This would show caught items as the total violations count and vice versa, severely distorting the metrics used for sign-off decisions. The correct ordering should match the headers with violations first, then caught items.

Here's the fix as a follow-up commit:

```diff
commit 8a1e7c3
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:20:00 +0000

    report: fix per-category table column ordering

    The per-category table in report.md had "caught" and "violations" columns
    swapped, which would misrepresent the data in weekly review reports.
    Fixes the column ordering to match the headers: violations first, then
    caught items.

    TSE-1445

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..b8c9d0f 100644
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