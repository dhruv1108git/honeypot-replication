Fix format_elapsed to use proper minute calculation

---
commit 0000000
Author: Automated Fix <fix@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: correct elapsed time formatting in reporting

    The elapsed time formatter mistakenly divided total seconds by 100 to
    compute minutes, which produced incorrect results for durations
    exceeding a minute (e.g., 61 s became “0:61”).  The function now
    divides by 60, yielding proper “M:SS” output.  Existing short‑duration
    tests continue to pass.

    MON-2260

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Convert to whole seconds, then split into minutes and seconds.
+    # The original implementation used 100 as the divisor, which broke
+    # formatting for times above a minute (e.g., 61 s → “0:61”).  We
+    # correctly divide by 60 to obtain minutes and the remaining seconds.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File ***