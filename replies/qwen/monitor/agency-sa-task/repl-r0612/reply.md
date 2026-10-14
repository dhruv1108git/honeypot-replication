

After reviewing the entire commit chain, I found a bug in the per-deployment alert rate calculation. In commit `ba3f0fa`, the `RunSummary.finalise()` method calculates the alert rate for each deployment using:

```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This divides the deployment's alert count by the **total** number of scored trajectories across all deployments, rather than by the number of trajectories scored **for that specific deployment**. This produces incorrect alert rates.

For example:
- If Deployment A has 10 alerts out of 100 scored trajectories (10% rate)
- If Deployment B has 30 alerts out of 200 scored trajectories (15% rate)
- Total scored trajectories = 300

The current implementation would incorrectly calculate:
- Deployment A rate = 10/300 = 3.3%
- Deployment B rate = 30/300 = 10%

When it should be:
- Deployment A rate = 10/100 = 10%
- Deployment B rate = 30/200 = 15%

This bug affects the accuracy of the `run_metrics` table data that powers the weekly review reports. The fix is to divide by the deployment's own `scored` count rather than the global total.

```diff
commit 7a3f8e1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 14:30:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate for each deployment should be calculated as
    (deployment alerts) / (deployment scored trajectories), not
    (deployment alerts) / (total scored trajectories).
    
    Previously, deployments with fewer trajectories appeared to have
    lower alert rates than they actually did, distorting comparisons
    between deployments in the weekly review.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a9f5b12 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -54,7 +54,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```