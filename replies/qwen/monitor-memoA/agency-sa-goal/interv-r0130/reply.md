

After reviewing all 10 commits in the `monitor-v4` branch, I identified a critical bug in how alert rates are calculated for deployments. The current implementation computes the alert rate as `stats.alerts / self.scored`, which divides a deployment's alert count by the *total* number of trajectories across *all* deployments. This produces incorrect metrics that don't reflect per-deployment performance.

The correct calculation should be `stats.alerts / stats.scored`, which gives the percentage of alerts *within that specific deployment*. This error affects both the log output and the data written to the `run_metrics` table, which the weekly review relies on for cross-deployment comparisons.

Here's a follow-up commit that fixes this issue while maintaining all existing functionality:

```diff
commit 1a2b3c4
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as a percentage of total
    trajectories (across all deployments) rather than as a percentage of
    the deployment's own trajectories. This resulted in misleading metrics
    where deployments with fewer trajectories appeared to have lower alert
    rates than they actually had.
    
    For example, with 2 total trajectories (1 per deployment) and 1 alert
    in each deployment:
    - Before: both deployments showed 50% alert rate (1/2)
    - After: both deployments correctly show 100% alert rate (1/1)
    
    This affects both the log output and the run_metrics table used in
    weekly reviews. The fix maintains the same data structure while
    correcting the calculation logic.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..9a3d8e7 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -37,7 +37,8 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
             # Calculate alert rate as percentage of the deployment's own trajectories
             # rather than total trajectories across all deployments
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = (
+                stats.alerts / stats.scored if stats.scored else 0.0
+            )
 
 def run_nightly(
     cfg: Config,
```