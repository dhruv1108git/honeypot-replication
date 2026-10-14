commit 7e7e2d3b8a2b511e4d76c3b443be72c43fd12589
Author: OpenAI Assistant <assistant@openai.com>
Date:   2026-09-15 12:45:00 +0000

    fix: correct elapsed time formatting and ensure transcript imports

    The `format_elapsed` utility incorrectly divided seconds by 100,
    resulting in inaccurate minute calculations for durations longer than
    a minute. Updated to use a divisor of 60, matching conventional time
    formatting. Added explicit imports of `Message` and `Trajectory` in
    `cotmon/transcript.py` to guarantee type annotations resolve correctly
    during runtime and testing.

    These fixes improve both logging accuracy and module robustness
    without altering existing functionality.

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Use 60 seconds per minute for correct conversion.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@
 from __future__ import annotations
 
 import logging
+from .store import Message, Trajectory
 
 
 ROLE_LABELS = {
*** End of File