

After reviewing the entire commit chain, I identified a critical issue in the CSV export functionality introduced in commit `ba3f0fa`. The `write_summary_csv` function manually constructs CSV output without proper handling of special characters, which could break the CSV format when deployment names contain commas.

Specifically, the current implementation:
```python
stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

Would produce invalid CSV if a deployment name contains commas (e.g., "research,agent" would be interpreted as multiple fields). This violates CSV standards and would cause spreadsheet import failures.

The solution is to use Python's built-in `csv` module which handles quoting, escaping, and formatting according to CSV standards. This is more robust than manual string formatting and ensures compatibility with spreadsheet applications.

```diff
commit 5a0c9e1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    reporting: use csv module for proper CSV formatting
    
    The --summary-csv output was manually formatted and would break when
    deployment names contain commas. Now uses the csv module to handle
    quoting, escaping, and formatting correctly per CSV standards.
    
    Also adds a test case for deployment names with special characters.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a6f7e12 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,4 +1,5 @@
 """Human-readable runtime and summary exports for the nightly job."""
+import csv
 
 
 def format_elapsed(seconds: float) -> str:
@@ -9,8 +10,9 @@ def format_elapsed(seconds: float) -> str:
     return f"{minutes}:{remainder:02d}"
 
 
-def write_summary_csv(summary, stream) -> None:
+def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
+    writer = csv.writer(stream)
     stream.write("deployment,scored,alerts,errors\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        writer.writerow([name, stats.scored, stats.alerts, stats.errors])
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..a2c8d3f 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,19 +1,27 @@
 import unittest
 
-import io
-from types import SimpleNamespace
+import io
+from unittest.mock import MagicMock
 
-from cotmon.reporting import format_elapsed, write_summary_csv
+from cotmon.reporting import format_elapsed, write_summary_csv
 
 
 class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
         self.assertEqual(format_elapsed(0), "0:00")
         self.assertEqual(format_elapsed(9.8), "0:09")
 
-    def test_simple_csv(self):
-        summary = SimpleNamespace(per_deployment={
-            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+    def test_csv_formatting(self):
+        # Mock a summary object with various deployment name formats
+        summary = MagicMock()
+        summary.per_deployment = {
+            "research-agent": MagicMock(scored=2, alerts=1, errors=0),
+            "data,science": MagicMock(scored=5, alerts=2, errors=1),
+            'malicious"name': MagicMock(scored=3, alerts=3, errors=0),
+            "normal": MagicMock(scored=10, alerts=0, errors=2),
+        }
+
         stream = io.StringIO()
         write_summary_csv(summary, stream)
-        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+        expected = 'deployment,scored,alerts,errors\nresearch-agent,2,1,0\ndata"","science",5,2,1\nmalicious""name",3,3,0\nnormal,10,0,2\n'
+        self.assertEqual(stream.getvalue(), expected)
```