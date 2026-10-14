

The review of the commit chain revealed a critical bug in the per-deployment alert rate calculation introduced in commit `ba3f0fa`. The `alert_rate` was incorrectly calculated as `(deployment alerts) / (total trajectories scored)` rather than `(deployment alerts) / (deployment trajectories scored)`. This would make per-deployment metrics misleading - for example, a high-risk deployment with few trajectories could appear safer than a low-risk deployment with many trajectories.

Specifically, in `RunSummary.finalise()`, the calculation used `self.scored` (total trajectories) instead of `stats.scored` (deployment-specific trajectories). This fundamentally breaks the purpose of per-deployment metrics, which should show each deployment's individual risk profile.

The fix changes the denominator to use the deployment's own trajectory count, ensuring alert rates accurately reflect per-deployment risk. This is essential for the weekly review process that compares deployments and monitor versions as mentioned in the README.

```diff
commit 9a2b1c7
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The per-deployment alert rate was incorrectly calculated as:
      (deployment alerts) / (total trajectories scored)
    rather than the correct:
      (deployment alerts) / (deployment trajectories scored)
    
    This bug would make high-risk deployments with few trajectories appear
    safer than low-risk deployments with many trajectories. For example:
    - Deployment A: 100 trajectories, 10 alerts → 10% rate (correct)
    - Deployment B: 10 trajectories, 5 alerts → 50% rate (correct)
    
    But with the bug:
    - Deployment A: 10/110 ≈ 9.1%
    - Deployment B: 5/110 ≈ 4.5% (reversing their actual risk)
    
    Fixes the calculation to use the deployment's own trajectory count as
    the denominator, ensuring metrics accurately reflect per-deployment risk.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a1b2c3d 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
             # Calculate alert rate as (alerts for this deployment) / (trajectories for this deployment)
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```