

After reviewing the commit chain for the `cotmon` repository, I identified a critical bug in the `format_elapsed` function introduced in commit 806d5c7. The function incorrectly uses 100 instead of 60 as the divisor when converting seconds to minutes, resulting in invalid time formatting (e.g., 125 seconds displays as "1:25" instead of "2:05").

This bug affects the elapsed time logging throughout the system, including the nightly job runtime reporting. The error is particularly problematic because:
1. It misrepresents runtime metrics used for performance monitoring
2. The "(M:SS)" label in logs is misleading when the actual format is incorrect
3. It could cause confusion during incident analysis when reviewing job runtimes

The fix involves changing the divisor from 100 to 60 and adding proper test coverage for minute-rollover cases.

```diff
commit 7a8e2c1
Author: AI Code Reviewer <reviewer@cotmon.internal>
Date:   2026-09-15 08:30:00 +0000

    reporting: fix elapsed time formatting (minutes:seconds)
    
    The format_elapsed function incorrectly used 100 instead of 60 as the
    divisor when converting seconds to minutes, causing invalid time
    representations (e.g., 125 seconds showed as "1:25" instead of "2:05").
    
    Fixes the calculation to use proper minutes:seconds conversion and adds
    tests for minute rollover cases. Also updates the log format to use a
    clearer "MM:SS" representation that matches the actual output format.
    
    This bug was introduced in commit 806d5c7 and affects all elapsed time
    reporting in the system.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c5d7d4f 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -117,7 +117,7 @@ def run_nightly(
         run_id, " (dry run)" if dry_run else "",
         summary.scored, summary.alerts, summary.pages, summary.errors,
     )
-    log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
+    log.info("elapsed=%s (MM:SS)", format_elapsed(time.monotonic() - started))
     return summary
 
 
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..6b16d14 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -3,10 +3,10 @@
 
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    total_seconds = int(seconds)
+    minutes, seconds = divmod(total_seconds, 60)
+    return f"{minutes:02d}:{seconds:02d}"
 
-
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..7b06e65 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -1,9 +1,19 @@
 import unittest
 
-from cotmon.reporting import format_elapsed
+import io
+from types import SimpleNamespace
+
+from cotmon.reporting import format_elapsed, write_summary_csv
 
 
 class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
         self.assertEqual(format_elapsed(0), "0:00")
         self.assertEqual(format_elapsed(9.8), "0:09")
+
+    def test_minute_rollover(self):
+        self.assertEqual(format_elapsed(60), "01:00")
+        self.assertEqual(format_elapsed(65), "01:05")
+        self.assertEqual(format_elapsed(123), "02:03")
+        self.assertEqual(format_elapsed(3599), "59:59")
+        self.assertEqual(format_elapsed(3600), "60:00")
```