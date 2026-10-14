fix: correct elapsed time formatting

The `format_elapsed` helper incorrectly used a divisor of 100 when converting seconds to minutes and seconds, resulting in inaccurate elapsed time representations for durations longer than 100 seconds. This fix updates the function to use the proper divisor of 60, ensuring correct minute‑second formatting across all runtime logs and preserving expected behavior for existing tests.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e6312f5 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Convert total seconds into minutes and seconds, using 60 seconds per minute.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```