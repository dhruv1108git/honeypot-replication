commit 9b9a2f4
Author: OpenAI ChatGPT <noreply@openai.com>
Date:   2026-09-15 12:00:00 +0000

    fix: correct elapsed time formatting in reporting

    The `format_elapsed` helper incorrectly divided seconds by 100, which
    produced nonsensical minute values for durations longer than a minute.
    Replace the divisor with 60 to format elapsed time as whole minutes and
    seconds (M:SS). The existing short‑duration tests still pass, and longer
    runs now report a proper time format.

    MON-2265

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..8aef2bc 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use 60 seconds per minute to get a proper M:SS format.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
*** End of File ***