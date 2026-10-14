commit 9f43e0d
Author: Automated Review Bot <bot@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: correct elapsed time formatting and per‑deployment alert rate calculation
    
    * `cotmon/reporting.format_elapsed` now divides seconds by 60 to produce
      proper minutes and seconds (M:SS) instead of using a base‑100 split.
      This aligns the implementation with its documentation and yields
      accurate runtime logs.
    
    * `cotmon/pipeline.RunSummary.finalise` now computes per‑deployment
      `alert_rate` as alerts divided by that deployment's own scored count,
      rather than the total scored across all deployments. This fixes the
      per‑deployment metrics stored in the `run_metrics` table and reported
      in logs.
    
    These changes ensure correct reporting and accurate metric aggregation
    without affecting existing functionality.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..0c3a2f1 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use base‑60 conversion for proper minute/second formatting.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
@@
 def write_summary_csv(summary, stream) -> None:
@@
     stream.write("deployment,scored,alerts,errors\n")
     for name, stats in sorted(summary.per_deployment.items()):
         stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..b9f6e3c 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 @dataclass
 class RunSummary:
@@
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
@@
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Calculate per‑deployment alert rates based on each deployment's own scores."""
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End of File ***