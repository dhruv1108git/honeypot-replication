

# report: fix swapped columns in per-category metrics table

In the per-category metrics table, the "violations" column was showing the
number of caught violations, and the "caught" column was showing the total
violations. This commit swaps them to display the correct values.

The per_category dictionary from metrics.py has:
- "violations": total violations in the category
- "caught": number of violations that were correctly flagged

The report now correctly displays:
| category | violations | caught | recall | benign flagged |
| cat      | total      | caught | ...    | ...            |

```diff
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..d5d5a1a 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@ -40,7 +40,7 @@ def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int =
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
```