

# fix: correct per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as `stats.alerts / global_total_scored` rather than `stats.alerts / stats.scored`. This meant the alert rate didn't accurately reflect the proportion of trajectories with alerts for that specific deployment - it was being normalized against the total across all deployments instead of the deployment's own count.

This bug would cause misleading metrics in the `run_metrics` table and any reports generated from it, potentially leading to incorrect conclusions about which deployments have higher safety concerns.

The fix changes the calculation to use the deployment's own scored count, which properly represents the alert rate for that specific deployment.

MON-2261

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c661a68 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```