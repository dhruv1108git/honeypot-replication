

fix(report): correct per-category table column order

The per-category table header listed columns as "category | violations | caught | recall | benign flagged"
but the data rows had caught first and violations second, causing a mismatch. This made the report misleading
as it appeared that caught > violations in some cases.

Fix by swapping the order in the data rows to match the header: violations first, then caught.

TSE-1445

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..c92b338 100644
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