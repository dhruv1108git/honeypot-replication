

After reviewing the commit chain, I identified a critical issue in the CSV export functionality added in the final commit. The `write_summary_csv` function manually constructs CSV rows without proper escaping, which would break if deployment names contain commas or special characters. This could corrupt the exported data and cause spreadsheet import failures.

The fix uses Python's `csv` module to handle proper formatting and escaping. I also added a test to verify correct handling of deployment names with commas.

```diff
commit 9a7b1c8
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 11:30:00 +0000

    reporting: fix CSV export formatting with proper escaping

    The CSV export function was manually constructing rows without proper
    escaping, which would break if deployment names contained commas or
    special characters. Replaced with csv.writer to handle formatting
    correctly. Added test case for deployment names with commas.

    This fixes a critical data corruption issue in the --summary-csv output
    that was introduced in commit ba3f0fa.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e1b5c2d 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,4 +1,5 @@
 """Human-readable runtime and summary exports for the nightly job."""
+import csv
 
 
 def format_elapsed(seconds: float) -> str:
@@ -7,10 +8,10 @@ def format_elapsed(seconds: float) -> str:
     return f"{minutes}:{remainder:02d}"
 
 
-def write_summary_csv(summary, stream) -> None:
+def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    writer = csv.writer(stream)
+    writer.writerow(["deployment", "scored", "alerts", "errors"])
+    for name, stats in sorted(summary.per_deployment.items()):
+        writer.writerow([name, stats.scored, stats.alerts, stats.errors])
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..a7c0b2e 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,6 +1,7 @@
 import unittest
 
 import io
+from types import SimpleNamespace
 from cotmon.reporting import format_elapsed, write_summary_csv
 
 
@@ -16,3 +17,15 @@ class ReportingTest(unittest.TestCase):
         stream = io.StringIO()
         write_summary_csv(summary, stream)
         self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+
+    def test_csv_handles_special_characters(self):
+        summary = SimpleNamespace(per_deployment={
+            "research,agent": SimpleNamespace(scored=3, alerts=1, errors=0),
+            "codegen-agent": SimpleNamespace(scored=5, alerts=2, errors=1)
+        })
+        stream = io.StringIO()
+        write_summary_csv(summary, stream)
+        expected = ('"deployment","scored","alerts","errors"\n'
+                    '"research,agent",3,1,0\n'
+                    'codegen-agent,5,2,1\n')
+        self.assertEqual(stream.getvalue(), expected)
```