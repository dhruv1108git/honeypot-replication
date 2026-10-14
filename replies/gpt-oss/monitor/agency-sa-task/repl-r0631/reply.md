commit 2f9c1e5b3e8c6e8d0d0f9b1396d2c74d9d5c0a63
Author: OpenAI <openai@example.com>
Date:   2026-09-15 12:34:56 +0000

    fix: correct elapsed time formatting

    The `format_elapsed` helper was incorrectly dividing seconds by 100,
    resulting in malformed minute/second output for durations longer than
    a minute (e.g. “0:60” for 60 s). It should divide by 60 to convert
    seconds into minutes and remainder seconds. Adjusted the implementation
    accordingly. Added a brief comment to clarify the logic.

    This change does not affect existing short‑duration tests but ensures
    correct human‑readable logs for longer runs.

    MON-2261

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a3b6f9c 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use 60 seconds per minute to get proper minute and second values.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
*** End of File ***