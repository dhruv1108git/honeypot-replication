fix: correct format_elapsed to use minutes of 60 seconds

The elapsed time formatter incorrectly divided seconds by 100, resulting in
incorrect minute values for durations longer than a minute. Updated the
implementation to divide by 60, matching the conventional M:SS format and
added a brief comment explaining the fix.

```diff
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # The original implementation mistakenly divided by 100, which produced
+    # incorrect minute values for durations longer than a minute.
+    # Use 60 seconds per minute to report proper elapsed time.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```