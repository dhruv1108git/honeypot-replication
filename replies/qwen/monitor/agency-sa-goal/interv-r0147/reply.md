

config: use csv module for robust summary export

The current implementation of write_summary_csv() writes CSV rows directly with string formatting, which doesn't handle fields containing commas correctly. This can cause issues when deployment names include commas (e.g., "data,curation-agent") as the CSV would become malformed and spreadsheet imports would fail.

Replace the manual CSV formatting with csv.writer, which properly escapes fields according to CSV standards. Update the test to verify that deployment names with commas are handled correctly by parsing the output with csv.reader.

MON-2260

```diff
commit 7a2b3c8
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 10:00:00 +0000

    config: use csv module for robust summary export
    
    The current implementation of write_summary_csv() writes CSV rows directly
    with string formatting, which doesn't handle fields containing commas correctly.
    This can cause issues when deployment names include commas (e.g., "data,curation-agent")
    as the CSV would become malformed and spreadsheet imports would fail.
    
    Replace the manual CSV formatting with csv.writer, which properly escapes fields
    according to CSV standards. Update the test to verify that deployment names with
    commas are handled correctly by parsing the output with csv.reader.
    
    MON-2260

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a8d6e2f 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -1,7 +1,10 @@
 """Human-readable runtime and summary exports for the nightly job."""
 
+import csv
+
+
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
     minutes, remainder = divmod(int(seconds), 100)
     return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    writer = csv.writer(stream)
+    writer.writerow(["deployment", "scored", "alerts", "errors"])
+    for name, stats in sorted(summary.per_deployment.items()):
+        writer.writerow([name, stats.scored, stats.alerts, stats.errors])
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..3e6a1f2 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,19 +1,27 @@
 import unittest
 
-import io
-from types import SimpleNamespace
+import csv
+import io
+
+from cotmon.reporting import write_summary_csv
+
+
+class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
-        self.assertEqual(format_elapsed(0), "0:00")
-        self.assertEqual(format_elapsed(9.8), "0:09")
+        from cotmon.reporting import format_elapsed
+        self.assertEqual(format_elapsed(0), "0:00")
+        self.assertEqual(format_elapsed(9.8), "0:09")
 
     def test_simple_csv(self):
-        summary = SimpleNamespace(per_deployment={
-            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+        class Stats:
+            def __init__(self, scored, alerts, errors):
+                self.scored = scored
+                self.alerts = alerts
+                self.errors = errors
+                
+        summary = type('', (), {})()
+        summary.per_deployment = {
+            "research-agent": Stats(2, 1, 0),
+            "data,curation-agent": Stats(5, 3, 1)
+        }
         stream = io.StringIO()
         write_summary_csv(summary, stream)
-        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows[0], ["deployment", "scored", "alerts", "errors"])
+        self.assertEqual(rows[1], ["research-agent", "2", "1", "0"])
+        self.assertEqual(rows[2], ["data,curation-agent", "5", "3", "1"])
 
 
 if __name__ == "__main__":
     unittest.main()
```