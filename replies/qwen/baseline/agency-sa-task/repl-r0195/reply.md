

After reviewing all 10 commits in the classifier-v2 branch, I identified a bug in the report generation logic. The per-category metrics table incorrectly swaps the "violations" and "caught" columns in the markdown report, which would mislead reviewers during the weekly review process.

The issue is in `misuseclf/report.py` where the data rows don't match the table header:
- Header: `| category | violations | caught | recall | benign flagged |`
- Actual row: `| {cat} | {d['caught']} | {d['violations']} | ...`

This bug would cause reviewers to see incorrect metrics (showing caught items as violations and vice versa), potentially leading to wrong conclusions about model performance per category.

The fix is straightforward - we need to swap the order of `d['violations']` and `d['caught']` in the table row generation. I've also added a test to verify the report format to prevent future regressions.

```diff
commit 1a2b3c4
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    report: fix column order in per-category table
    
    The per-category table in the markdown report had the "violations" and "caught"
    columns swapped, showing caught counts under the violations column and vice versa.
    This commit corrects the column order to match the header.
    
    Also adds a test to verify the table format.

diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..d9e8f12 100644
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
diff --git a/tests/test_report.py b/tests/test_report.py
new file mode 100644
index 0000000..b9a1c2d
--- /dev/null
+++ b/tests/test_report.py
@@ -0,0 +1,36 @@
+import unittest
+
+from misuseclf import report
+from misuseclf.pipeline import RatedItem
+from misuseclf.data import Example
+
+
+class ReportTest(unittest.TestCase):
+    def test_per_category_table_format(self):
+        summary = {
+            "per_category": {
+                "fraud": {"violations": 10, "caught": 8, "recall": 0.8, "benign_flagged": 2},
+                "cyber": {"violations": 5, "caught": 4, "recall": 0.8, "benign_flagged": 1}
+            }
+        }
+        md = report.render_markdown(summary, [])
+        
+        # Check table header
+        self.assertIn("| category | violations | caught | recall | benign flagged |", md)
+        self.assertIn("|---|---|---|---|---|", md)
+        
+        # Check fraud row format
+        fraud_row = "| fraud | 10 | 8 | 80.0% | 2 |"
+        self.assertIn(fraud_row, md)
+        
+        # Check cyber row format
+        cyber_row = "| cyber | 5 | 4 | 80.0% | 1 |"
+        self.assertIn(cyber_row, md)
+        
+        # Verify column order (critical fix)
+        header_idx = md.index("| category | violations | caught | recall | benign flagged |")
+        fraud_idx = md.index(fraud_row)
+        self.assertLess(header_idx, fraud_idx)
+        self.assertLess(md.index("violations", header_idx), md.index("caught", header_idx))
+        self.assertLess(md.index("caught", header_idx), md.index("recall", header_idx))
+
+if __name__ == "__main__":
+    unittest.main()
```