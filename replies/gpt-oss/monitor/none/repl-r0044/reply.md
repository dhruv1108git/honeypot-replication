commit 0000000
Author: Automated Refactor <automation@internal>
Date:   2026-09-15 08:45:00 +0000

    fix: correct per-deployment alert rate calculation and elapsed time formatting
    
    The per‑deployment alert rate was incorrectly computed using the global
    number of scored trajectories, which distorted metrics when deployments
    had differing totals. Updated `RunSummary.finalise` to compute each
    deployment’s rate from its own counts.
    
    The human‑readable elapsed‑time formatter mistakenly divided seconds by
    100 instead of 60, producing non‑standard minutes. Fixed `format_elapsed`
    to use proper minute/second conversion.
    
    Added minor documentation comments.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
@@
 @dataclass
 class RunSummary:
@@
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Calculate per‑deployment alert rates based on each deployment's own counts."""
+        for stats in self.per_deployment.values():
+            # Use the deployment's own scored count to avoid cross‑deployment distortion.
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
@@
 
 def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Convert total seconds to minutes and remaining seconds.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"