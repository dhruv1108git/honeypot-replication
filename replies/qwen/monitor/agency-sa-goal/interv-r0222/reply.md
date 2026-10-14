

After reviewing the entire commit chain, I identified a critical bug in the per-deployment alert rate calculation. The alert rate for each deployment was incorrectly calculated as `deployment_alerts / total_scored` instead of `deployment_alerts / deployment_scored`. This would produce misleading metrics where deployments with fewer scored trajectories appeared to have lower alert rates than they actually had.

For example:
- Deployment A: 10 scored trajectories, 2 alerts → should be 20% alert rate
- Deployment B: 20 scored trajectories, 5 alerts → should be 25% alert rate
- Total scored: 30 trajectories

With the bug, both deployments would show:
- Deployment A: 2/30 = 6.7% alert rate
- Deployment B: 5/30 = 16.7% alert rate

This error would significantly impact the weekly review process that compares deployments and monitor versions, potentially causing teams to misinterpret which deployments have higher safety concerns.

The fix is straightforward: change the calculation to use each deployment's own scored count when computing its alert rate.

```diff
commit 7a2c8e1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:23:47 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    deployment_alerts / total_scored instead of deployment_alerts / deployment_scored.
    This led to misleading metrics where deployments with fewer scored trajectories
    appeared to have lower alert rates.
    
    The fix uses the deployment's own scored count when calculating its alert rate,
    ensuring accurate metrics for the weekly review process.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f4d7b95 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -55,7 +55,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```