### Commit Message
Fix inaccurate elapsed time formatting in reporting utilities  

The `format_elapsed` helper incorrectly split seconds into minutes using a divisor of 100, leading to misleading runtime logs. Updated implementation now correctly uses a 60‑second minute conversion, ensuring accurate M:SS output across all durations. Added a concise comment to clarify the conversion.

### Diff
```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e2f3c1b 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 
 def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Convert total seconds to minutes and remaining seconds.
+    # The original implementation mistakenly used 100 seconds per minute,
+    # which produced incorrect runtime logs (e.g. 120 s → “1:20” instead of “2:00”).
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
```