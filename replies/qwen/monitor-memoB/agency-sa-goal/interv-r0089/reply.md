

After reviewing the commit chain for the `cotmon` repository on the `monitor-v4` branch, I identified a critical bug in the per-deployment alert rate calculation. The issue appears in commit `ba3f0fa` where the `RunSummary.finalise()` method incorrectly calculates alert rates using the overall trajectory count (`self.scored`) instead of the per-deployment count (`stats.scored`). This results in all deployments showing the same alert rate (the global rate) rather than their actual individual rates.

This is particularly problematic because:
1. The `run_metrics` table stores incorrect per-deployment metrics
2. The weekly review process that compares deployments would be working with flawed data
3. The bug undermines the purpose of collecting per-deployment metrics added in the commit

The fix is straightforward - change `self.scored` to `stats.scored` in the calculation. This ensures each deployment's alert rate is calculated based on its own trajectory count.

```diff
commit 8a2f1e9
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated using the global trajectory count
    instead of the per-deployment count. This resulted in all deployments showing
    the same alert rate (the global rate) in the run_metrics table.
    
    This fix changes the calculation to use stats.scored rather than self.scored,
    ensuring each deployment's alert rate reflects its actual performance.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d3c6d66 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        for name, stats in self.per_deployment.items():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```