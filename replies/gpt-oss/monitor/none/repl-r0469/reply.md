Fix elapsed time formatting bug and improve documentation

The `format_elapsed` function incorrectly used a divisor of 100 when converting seconds to minutes, resulting in inaccurate formatting for durations over a minute. Updated to use the correct divisor of 60 and clarified the docstring.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a1c2d9e 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    """Format elapsed seconds as whole minutes and seconds (M:SS).
+
+    The function now correctly uses 60 seconds per minute.
+    """
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```