

After reviewing the commit chain, I identified a critical bug in the markdown report generation. The per-category table incorrectly swaps "violations" and "caught" columns in the data rows while the header labels remain correct. This would misrepresent the metrics during the weekly review, showing caught violations as total violations and vice versa.

The issue is in `report.py` where the table rows are constructed:
```python
lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

This should instead match the header order:
```python
lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```

Additionally, I noticed the report doesn't properly handle the case where `d['violations']` is zero (which would cause division by zero in recall calculation), though the metrics code already handles this with `_ratio()`. The fix ensures the report accurately reflects the per-category metrics.

Here's the follow-up commit:

```diff
fix(report): correct per-category table column order in markdown report

The per-category table in the markdown report had swapped "violations" and
"caught" columns in the data rows while the header labels were correct.
This misrepresented the metrics during the weekly review, showing caught
violations as total violations and vice versa.

The issue was in report.py where the table rows were constructed with
d['caught'] in the violations column position and d['violations'] in the
caught column position. Fixed to match the header order.

This ensures the report accurately reflects per-category metrics for the
weekly review.

TSE-1449
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..c67c1a4 100644
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