

# report: fix swapped violations and caught columns in per-category table

The per-category table in the markdown report had "violations" and "caught"
columns swapped in the data rows, which made the numbers confusing to interpret.
The table headers correctly showed "violations | caught" but the data displayed
"caught | violations" - showing the number of caught violations under the
violations column and vice versa.

This commit fixes the column order to match the headers: violations (total
violations in the category) followed by caught (number of violations caught).
This makes the table intuitive to read and aligns with how the weekly review
team analyzes the results.

TSE-1448

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..a9f3e5d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -32,7 +32,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```