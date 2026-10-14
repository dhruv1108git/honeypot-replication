Fix elapsed time formatting to use correct minute conversion

The `format_elapsed` utility incorrectly used a divisor of 100, leading to
minutes being calculated as every 100 seconds instead of 60. This broke
the intended M:SS format for elapsed times. Updated the implementation to
use `divmod(int(seconds), 60)` and added a brief comment explaining the
logic.

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
+    # 60 seconds make a minute – use divmod to split total seconds
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```