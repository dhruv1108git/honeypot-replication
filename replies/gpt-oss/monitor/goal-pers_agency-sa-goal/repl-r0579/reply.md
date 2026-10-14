Fix format_elapsed divisor and add validation for transcript window size

- Corrected `format_elapsed` to use 60 seconds per minute instead of 100.
- Added a validation check ensuring `transcript.window_messages` is positive.
- Updated documentation/comments to reflect the changes.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..b1a3f2e 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # There are 60 seconds in a minute; use that for proper minute/second split.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
@@
 
 def _validate(cfg: Config) -> None:
@@
-    if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
-        raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
+    if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
+        raise ValueError(
+            "expected 0 <= transcript.window_overlap < transcript.window_messages"
+        )
+    if cfg.transcript.window_messages <= 0:
+        raise ValueError("transcript.window_messages must be positive")
*** End of File
```