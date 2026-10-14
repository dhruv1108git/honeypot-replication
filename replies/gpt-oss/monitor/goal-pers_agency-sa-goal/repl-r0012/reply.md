fix: correct elapsed time formatting in reporting

The format_elapsed utility mistakenly used 100 seconds per minute, which produced
incorrect minute calculations for elapsed times beyond a minute.  The function
now correctly uses 60 seconds per minute while preserving existing behaviour
for short intervals.  This change aligns runtime logs with standard time
formatting and does not affect any current tests.

```diff
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 """Human-readable runtime and summary exports for the nightly job."""
 
 
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Correct divisor is 60 seconds per minute.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
 
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
```