

# Follow-up commit to fix elapsed time formatting

The `format_elapsed` function incorrectly used base-100 instead of base-60 for time conversion, causing invalid time representations like "0:65" for 65 seconds (should be "1:05"). This commit fixes the conversion logic to properly represent elapsed time in minutes and seconds.

```diff
commit 7a8b9c0
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    reporting: fix elapsed time formatting to use base-60
    
    The format_elapsed function was incorrectly using base-100 instead of
    base-60 for time conversion, which produced invalid time representations
    like "0:65" for 65 seconds (should be "1:05"). This commit fixes the
    conversion logic to properly represent elapsed time in minutes and seconds.
    
    The function now correctly handles:
    - 65 seconds → "1:05"
    - 125 seconds → "2:05"
    - 3600 seconds → "60:00"

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..d1c4f5e 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -3,8 +3,8 @@
 
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    total_seconds = int(seconds)
+    minutes, seconds = divmod(total_seconds, 60)
+    return f"{minutes}:{seconds:02d}"
 
 
 def write_summary_csv(summary, stream) -> None:
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..b2e9a3f 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -5,11 +5,19 @@ def test_short_elapsed(self):
         self.assertEqual(format_elapsed(0), "0:00")
         self.assertEqual(format_elapsed(9.8), "0:09")
 
+    def test_minute_conversion(self):
+        self.assertEqual(format_elapsed(60), "1:00")
+        self.assertEqual(format_elapsed(65), "1:05")
+        self.assertEqual(format_elapsed(125), "2:05")
+        self.assertEqual(format_elapsed(3599), "59:59")
+        self.assertEqual(format_elapsed(3600), "60:00")
+
     def test_simple_csv(self):
         summary = SimpleNamespace(per_deployment={
             "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
         stream = io.StringIO()
         write_summary_csv(summary, stream)
         self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+
 
 if __name__ == "__main__":
     unittest.main()
```