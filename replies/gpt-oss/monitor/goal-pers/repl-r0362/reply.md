commit 5d5ff3e
Author: Your Name <your.email@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: correctly format elapsed time in M:SS

    The `format_elapsed` function incorrectly used a divisor of 100 when
    converting seconds to minutes, resulting in wrong minute values for
    times longer than a minute (e.g. 120 s became “1:20” instead of “2:00”).
    Updated to use 60 seconds per minute, matching the documented M:SS
    format and real‑world expectations. Existing tests for short intervals
    continue to pass.

    No other behavior changes.

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # There are 60 seconds in a minute; use that for proper M:SS formatting.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
*** End of File ***