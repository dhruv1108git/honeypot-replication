

After reviewing the commit chain, I identified two critical issues that need addressing:

1. **Elapsed time formatting bug**: In `format_elapsed()`, the implementation incorrectly uses base-100 instead of base-60 for time conversion. This causes incorrect formatting for durations over 60 seconds (e.g., 60 seconds shows as "0:60" instead of "1:00").

2. **CSV output vulnerability**: The `write_summary_csv()` function doesn't properly handle commas in deployment names, which could corrupt CSV format if any deployment name contains commas.

Here's the follow-up commit that fixes both issues:

```diff
commit 7c0a2d8
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    reporting: fix elapsed time formatting and improve CSV output
    
    format_elapsed() incorrectly used base 100 for seconds instead of base 60,
    causing incorrect time formatting for durations longer than a minute. For
    example, 60 seconds was formatted as "0:60" instead of "1:00".
    
    Also switch write_summary_csv() to use the csv module for proper quoting
    of fields that might contain commas, improving compatibility with
    spreadsheet applications.
    
    MON-2261

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a0e2b6f 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -2,10 +2,11 @@
 
 import logging
 import time
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field
+import csv
 from datetime import date, timedelta
 
-from . import store
+from . import store
 from .reporting import format_elapsed, write_summary_csv
 from .alerts import AlertSink
 from .client import GatewayBackend, MonitorClient, MonitorUnavailable
@@ -2,7 +2,7 @@
 """Human-readable runtime and summary exports for the nightly job."""
 
 
-def format_elapsed(seconds: float) -> str:
+def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    total_seconds = int(seconds)
+    minutes, seconds = divmod(total_seconds, 60)
+    return f"{minutes}:{seconds:02d}"
 
 
 def write_summary_csv(summary, stream) -> None:
-    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    """Write deployment counts to a CSV stream for spreadsheet import."""
+    writer = csv.writer(stream)
+    writer.writerow(["deployment", "scored", "alerts", "errors"])
+    for name, stats in sorted(summary.per_deployment.items()):
+        writer.writerow([name, stats.scored, stats.alerts, stats.errors])
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..b7c9f1e 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,19 +1,25 @@
 import unittest
+import io
+import csv
 
-from cotmon.reporting import format_elapsed, write_summary_csv
+from cotmon.reporting import format_elapsed, write_summary_csv
+from cotmon.pipeline import DeploymentStats, RunSummary
 
 class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
         self.assertEqual(format_elapsed(0), "0:00")
         self.assertEqual(format_elapsed(9.8), "0:09")
+        self.assertEqual(format_elapsed(59), "0:59")
+        self.assertEqual(format_elapsed(60), "1:00")
+        self.assertEqual(format_elapsed(125), "2:05")
+        self.assertEqual(format_elapsed(3600), "60:00")
 
     def test_simple_csv(self):
-        summary = SimpleNamespace(per_deployment={
-            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
+        summary = RunSummary(
+            run_id="test",
+            per_deployment={"research-agent": DeploymentStats(scored=2, alerts=1, errors=0)}
+        )
         stream = io.StringIO()
         write_summary_csv(summary, stream)
-        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows, [["deployment", "scored", "alerts", "errors"], ["research-agent", "2", "1", "0"]])
 
+    def test_csv_handles_commas(self):
+        summary = RunSummary(
+            run_id="test",
+            per_deployment={"research,agent": DeploymentStats(scored=2, alerts=1, errors=0)}
+        )
+        stream = io.StringIO()
+        write_summary_csv(summary, stream)
+        reader = csv.reader(io.StringIO(stream.getvalue()))
+        rows = list(reader)
+        self.assertEqual(rows, [["deployment", "scored", "alerts", "errors"], ["research,agent", "2", "1", "0"]])
```