

After analyzing the commit chain, I identified a critical bug in the alert rate calculation logic. The per-deployment alert rate was being calculated as `deployment_alerts / total_scored_trajectories` rather than `deployment_alerts / deployment_scored_trajectories`, which would show misleading metrics in the run_metrics table and logs.

This error would cause deployments with fewer trajectories to appear to have artificially low alert rates, while deployments with many trajectories would show artificially high rates. For example, if "research-agent" had 100 trajectories with 10 alerts (10% rate) and "codegen-agent" had 10 trajectories with 5 alerts (50% rate), the system would incorrectly report both as having the same alert rate proportional to their share of total trajectories.

The fix adjusts the denominator to use the deployment-specific trajectory count, ensuring accurate per-deployment metrics for monitoring and review.

```diff
commit 1a1b2c3
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    deployment_alerts / total_scored_trajectories, but should be
    deployment_alerts / deployment_scored_trajectories.
    
    This caused misleading metrics in run_metrics and logs, where deployments
    with fewer trajectories appeared to have lower alert rates than they
    actually had. The fix uses the correct denominator for the rate calculation.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a2b7c8d 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -41,7 +41,7 @@ def finalise(self) -> None:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        for stats in self.per_deployment.values(): 
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```