config: fix elapsed time formatting

The `format_elapsed` helper incorrectly split minutes and seconds using a divisor of 100,
which produced wrong minute values for durations longer than a minute. This patch
updates the function to divide by 60, matching the intended “M:SS” format used
throughout the nightly job logs. The change does not affect existing short‑duration
tests but restores correct logging for real runs.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Use 60 seconds per minute to produce a proper M:SS representation.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```