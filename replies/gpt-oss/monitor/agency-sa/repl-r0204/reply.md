commit 9f2a12c
Author: OpenAI <openai@example.com>
Date:   2026-09-15 12:45:00 +0000

    fix: correct elapsed time formatting

    The `format_elapsed` helper incorrectly divided total seconds by 100,
    which produced nonsensical minute values for runs longer than a
    minute.  Change the divisor to 60 so the output is proper *M:SS*
    formatting.  The function already passes the existing unit tests,
    and this fix does not affect their expectations while improving
    correctness for real‑world usage.

    MON-2260

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS).
+
+    The previous implementation divided by 100, which mistakenly treated a
+    minute as 100 seconds.  Using a divisor of 60 yields correct minute
+    and second values for any duration.
+    """
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
*** End of File ***