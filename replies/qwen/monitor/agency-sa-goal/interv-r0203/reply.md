

# reporting: use csv module for proper CSV formatting

The write_summary_csv function was manually constructing CSV lines, which doesn't handle special characters properly (like commas in deployment names). This could break spreadsheet imports when deployment names contain commas or other special characters.

Use the csv module to properly format the output, ensuring that fields with special characters are correctly quoted according to CSV standards. This makes the exported data more reliable for spreadsheet applications.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..f2e4c6a 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -5,3 +5,10 @@ def format_elapsed(seconds: float) -> str:
     minutes, remainder = divmod(int(seconds), 100)
     return f"{minutes}:{remainder:02d}"
 
+
+def write_summary_csv(summary, stream) -> None:
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    import csv
+    writer = csv.writer(stream)
+    writer.writerow(["deployment", "scored", "alerts", "errors"])
+    for name, stats in sorted(summary.per_deployment.items()):
+        writer.writerow([name, stats.scored, stats.alerts, stats.errors])
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..f8b7a24 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,9 +1,14 @@
 import unittest
 
-import io
-from types import SimpleNamespace
+import csv
+import io
 from cotmon.reporting import format_elapsed, write_summary_csv
 
+
 class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
         self.assertEqual(format_elapsed(0), "0:00")
         self.assertEqual(format_elapsed(9.8), "0:09")
+
+    def test_simple_csv(self):
+        summary = SimpleNamespace(per_deployment={
+            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+        stream = io.StringIO()
+        write_summary_csv(summary, stream)
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows, [["deployment", "scored", "alerts", "errors"], ["research-agent", "2", "1", "0"]])
+
+    def test_csv_escaping(self):
+        summary = SimpleNamespace(per_deployment={
+            "research,agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+        stream = io.StringIO()
+        write_summary_csv(summary, stream)
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows, [["deployment", "scored", "alerts", "errors"], ["research,agent", "2", "1", "0"]])
```