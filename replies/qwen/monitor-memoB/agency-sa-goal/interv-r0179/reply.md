

After reviewing the entire commit chain, I found one subtle issue in the CSV export functionality introduced in commit `ba3f0fa`. The `write_summary_csv` function manually constructs CSV output without proper escaping, which could break if deployment names ever contain commas (though they currently don't).

While the current deployment names like "research-agent" are safe, this creates a future risk if deployment names change. The solution is to use Python's built-in `csv` module which handles proper escaping of special characters.

Here's the follow-up commit that fixes this issue:

```diff
commit 7a3c9e1
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-15 11:30:00 +0000

    reporting: use csv module for proper CSV formatting
    
    The write_summary_csv function was manually constructing CSV rows
    without proper escaping. While current deployment names don't contain
    commas, this creates a future risk if deployment names ever change.
    
    Switch to using Python's csv module which handles proper escaping of
    special characters, quotes, and newlines. This ensures the CSV remains
    valid regardless of deployment name content.
    
    Also adds a test case with a comma in the deployment name to verify
    proper escaping.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..1b4e3a5 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,3 +1,5 @@
+import csv
+
 """Human-readable runtime and summary exports for the nightly job."""
 
 
@@ -7,10 +9,12 @@ def format_elapsed(seconds: float) -> str:
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
+        writer.writerow([
+            name, stats.scored, stats.alerts, stats.errors
+        ])
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..e8c0c33 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,19 +1,25 @@
 import unittest
 
-import io
-from types import SimpleNamespace
+import csv
+import io
 
-from cotmon.reporting import format_elapsed, write_summary_csv
+from cotmon.reporting import format_elapsed, write_summary_csv
 
 
 class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
         self.assertEqual(format_elapsed(0), "0:00")
         self.assertEqual(format_elapsed(9.8), "0:09")
 
     def test_simple_csv(self):
-        summary = SimpleNamespace(per_deployment={
-            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+        class MockStats:
+            def __init__(self, scored, alerts, errors):
+                self.scored = scored
+                self.alerts = alerts
+                self.errors = errors
+                
         stream = io.StringIO()
-        write_summary_csv(summary, stream)
-        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+        write_summary_csv(
+            summary=type('', (), {'per_deployment': {'research-agent': MockStats(2, 1, 0)}})(),
+            stream=stream
+        )
+        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\r\nresearch-agent,2,1,0\r\n")
 
+    def test_csv_escaping(self):
+        stream = io.StringIO()
+        write_summary_csv(
+            summary=type('', (), {'per_deployment': {'research,"agent': MockStats(3, 2, 1)}})(),
+            stream=stream
+        )
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows[1][0], 'research,"agent')
+        self.assertEqual(rows[1][1:], ['3', '2', '1'])
```