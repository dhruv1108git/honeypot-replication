commit f2d5c9e
Author: Automated Reviewer <reviewer@internal>
Date: 2026-09-15 12:31:22 +0000

    fix: correct elapsed time formatting and per‑deployment alert rate calculation
    
    The `format_elapsed` helper incorrectly used a divisor of 100 seconds per minute,
    which produced misleading runtimes for jobs longer than a minute. Updated to
    use the proper 60‑second divisor.
    
    `RunSummary.finalise` previously computed per‑deployment alert rates using the
    total number of scored trajectories for the entire run, which inflated the
    rates for deployments with fewer samples. Adjusted to calculate each
    deployment's alert rate based on its own scored count.
    
    These fixes resolve minor bugs and improve the accuracy of reporting and
    metrics without affecting existing functionality or tests.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..7c4caa2 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Use 60 seconds per minute, not 100, to correctly reflect wall‑clock time.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
 
 def write_summary_csv(summary, stream) -> None:
@@
 @dataclass
 class RunSummary:
@@
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Calculate per‑deployment alert rates based on each deployment's own scores."""
+        for stats in self.per_deployment.values():
+            # Guard against division by zero when a deployment has no scored trajectories.
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End of File ***