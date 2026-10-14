Fix elapsed time formatting to use minutes correctly

The `format_elapsed` function incorrectly divided total seconds by 100, leading to
incorrect minute calculations for durations longer than a minute. The divisor
should be 60 to convert seconds to minutes. Updated the implementation to use
the proper conversion while preserving existing behavior for short intervals.

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
+    # Convert seconds to minutes and remaining seconds (base 60).
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```