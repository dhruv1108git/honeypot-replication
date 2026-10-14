

# report: fix per-category table column order

The per-category metrics table in the markdown report had its "violations" and "caught" columns reversed relative to the header, causing confusion during weekly reviews. This commit corrects the column order to match the header description.

The table now correctly shows:
- violations: total violations in the category
- caught: number of those violations that were correctly flagged (used to calculate recall)

This aligns with how the metrics are calculated in `metrics.per_category()` where "violations" is the total count and "caught" is the subset correctly identified.

TSE-1449

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..c8c0d3d 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -35,7 +35,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     lines += ["", f"## False positives ({len(fps)})", ""]
     lines += _example_rows(fps, max_examples, clip) if fps else ["None."]
```