commit ffb9e1c
Author: Automated Refactor <refactor@internal>
Date:   2026-09-15 12:34:56 +0000

    fix: correct elapsed time formatting and per‑deployment alert rate calculation

    * `format_elapsed` now uses a 60‑second minute basis instead of 100,
      matching the intended “M:SS” format.
    * `RunSummary.finalise` now computes each deployment’s alert rate
      from its own scored count rather than the overall run count.
      This yields accurate per‑deployment metrics for `run_metrics`.

    These changes improve reporting accuracy and prevent misleading
    alert‑rate values in the `run_metrics` table.

    Addresses potential inconsistencies highlighted by the test suite.

--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Use a conventional 60‑second minute to produce proper minute/second values.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 @dataclass
 class RunSummary:
@@
-    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
+    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
@@
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Compute per‑deployment alert rates based on each deployment's own scores."""
+        for stats in self.per_deployment.values():
+            # Avoid division by zero; an alert rate of 0.0 is appropriate when no scores.
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End of File