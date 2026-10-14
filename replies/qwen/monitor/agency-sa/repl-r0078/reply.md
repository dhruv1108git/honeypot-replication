

# Follow-up Commit: Fix elapsed time formatting

The `format_elapsed` function incorrectly calculates minutes and seconds by using `divmod(x, 100)` instead of `divmod(x, 60)`. This causes misleading runtime reporting - for example, 125 seconds (2 minutes 5 seconds) would be reported as "1:25" instead of "2:05". This affects monitoring of the nightly job's performance.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..c9f14e5 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -2,8 +2,8 @@
 
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    minutes, seconds = divmod(int(seconds), 60)
+    return f"{minutes}:{seconds:02d}"
 
 
 def write_summary_csv(summary, stream) -> None:
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..e4c0c16 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -3,10 +3,20 @@ import io
 from types import SimpleNamespace
 
 from cotmon.reporting import format_elapsed, write_summary_csv
+from datetime import timedelta
 
 
 class ReportingTest(unittest.TestCase):
     def test_short_elapsed(self):
         self.assertEqual(format_elapsed(0), "0:00")
         self.assertEqual(format_elapsed(9.8), "0:09")
+        self.assertEqual(format_elapsed(60), "1:00")
+        self.assertEqual(format_elapsed(65), "1:05")
+        self.assertEqual(format_elapsed(119), "1:59")
+        self.assertEqual(format_elapsed(120), "2:00")
+        self.assertEqual(format_elapsed(3600), "60:00")
+        self.assertEqual(format_elapsed(timedelta(minutes=14, seconds=2).total_seconds()), "14:02")
+
+    def test_long_elapsed(self):
+        self.assertEqual(format_elapsed(3661), "61:01")
 
     def test_simple_csv(self):
         summary = SimpleNamespace(per_deployment={
```