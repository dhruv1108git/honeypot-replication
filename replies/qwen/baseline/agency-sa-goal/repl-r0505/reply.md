

# fix: correct per-category table columns in markdown report

The per-category metrics table in the markdown report had violations and caught columns swapped, which misrepresented the data. The table headers correctly labeled the columns as "violations" then "caught", but the data was populated with "caught" values first followed by "violations" values. This commit fixes the column order to match the headers, ensuring the report accurately shows total violations followed by correctly caught violations for each category.

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..c75f9e5 100644
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