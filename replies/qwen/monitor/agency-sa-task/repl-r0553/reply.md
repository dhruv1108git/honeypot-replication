

After reviewing the entire commit chain, I identified a critical bug in the per-deployment metrics calculation. The alert rate was incorrectly calculated using the total number of scored trajectories across *all* deployments rather than the deployment-specific count. This would produce misleading metrics where a deployment's alert rate was influenced by traffic volume in other deployments.

For example, if:
- `research-agent` had 5 alerts out of 10 scored trajectories
- `codegen-agent` had 1 alert out of 10 scored trajectories

The incorrect calculation would show `research-agent`'s alert rate as 5/20 = 0.25 instead of the correct 5/10 = 0.50. This would severely impact the weekly review's ability to compare deployment safety characteristics.

The fix is straightforward: use the deployment's own scored count when calculating its alert rate.

```diff
commit 9a2c1d8
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    metrics: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    deployment.alerts / total.scored instead of deployment.alerts / deployment.scored.
    This led to misleading metrics where the alert rate depended on traffic in other
    deployments. For example, a deployment with 5 alerts out of 10 scored trajectories
    would show an alert rate of 0.25 if there were 20 total trajectories across all
    deployments.
    
    Fix by using the deployment's own scored count in the rate calculation.
    
    MON-2265

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f12c1d0 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -41,7 +41,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```