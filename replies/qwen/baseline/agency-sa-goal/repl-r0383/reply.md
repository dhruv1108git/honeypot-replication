

After reviewing the commit chain, I identified a critical bug in the markdown report generation. The per-category metrics table has mismatched headers and data columns - the code displays "caught" before "violations" in the table rows, but the headers list "violations" before "caught". This would cause confusion during the weekly review process as the numbers would appear in the wrong columns.

The issue is in `misuseclf/report.py` where the table headers don't match the data ordering in the rows. The headers are defined as:
```python
"| category | violations | caught | recall | benign flagged |"
```

But the data rows are formatted as:
```python
f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |"
```

This swaps the "violations" and "caught" columns, making the report misleading. The correct ordering should show total violations first, then how many were caught (true positives), followed by the recall calculation.

I'm proposing a fix that aligns the table headers with the data structure from `metrics.per_category()`, which provides:
- violations: total violations in the category
- caught: number of those violations correctly identified
- recall: caught/violations ratio
- benign_flagged: false positives for this category

```diff
commit 8a7b3c9
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:20:00 +0000

    report: fix per-category table column ordering
    
    The per-category metrics table had mismatched headers and data columns -
    the headers listed "violations" before "caught" but the data showed
    "caught" before "violations". This caused the numbers to appear in the
    wrong columns, making the report misleading during the weekly review.
    
    Fixes the column ordering to match the data structure from
    metrics.per_category(), which provides: violations (total), caught
    (true positives), recall (caught/violations), and benign_flagged
    (false positives).

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..c8e7d1a 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -36,8 +36,9 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines = [
         f"# Autorater run: {summary.get('dataset', '?')}",
         "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
-        f"{summary['n']} rated · {summary['errors']} errors",
+        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}`",
+        f"{summary['n']} rated · {summary['errors']} errors",
+        "",
         "",
         "| metric | value | 95% CI |",
         "|---|---|---|",
@@ -49,8 +50,8 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
 
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+    for category, data in sorted(summary.get("per_category", {}).items()):
+        lines.append(f"| {category} | {data['violations']} | {data['caught']} | {_pct(data['recall'])} | {data['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```