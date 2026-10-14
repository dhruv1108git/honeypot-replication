commit 9c3d0a12a5f4d8c98c5a2be6d1f6b2c6c1d3e5a6
Author: Code Reviewer <code.reviewer@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: correct elapsed time formatting in reporting utils

    The `format_elapsed` function incorrectly used a divisor of 100 when
    converting total seconds into minutes and seconds, resulting in
    nonsensical minute values for durations longer than a minute. The
    function now correctly uses 60 seconds per minute, preserving the
    intended M:SS format. This change does not affect existing short-
    duration tests but ensures accurate logging for real‑world runs.

    MON-2259

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # There are 60 seconds in a minute; use integer division to get minutes
+    # and the remainder for the seconds component.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
*** End of File ***