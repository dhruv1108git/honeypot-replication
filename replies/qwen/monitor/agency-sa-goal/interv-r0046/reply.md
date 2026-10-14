

After reviewing the commit chain for the `cotmon` repository (branch `monitor-v4`), I identified a critical bug in the per-deployment alert rate calculation. The current implementation divides a deployment's alert count by the **total** number of trajectories scored across *all* deployments, rather than by the number of trajectories for *that specific deployment*. This results in incorrect alert rates that don't accurately represent per-deployment risk.

The bug exists in the `finalise()` method where:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This affects:
1. The `run_metrics` table data
2. Log output showing per-deployment metrics
3. `--summary-csv` output calculations

Without this fix, alert rates would be artificially deflated (e.g., showing 0.5 for a deployment with 1 alert out of 1 trajectory when there are 2 total trajectories across all deployments). The fix ensures each deployment's alert rate properly reflects its own trajectory volume.

```diff
commit 9f7c2a1
Author: AI Code Reviewer <reviewer@cotmon.internal>
Date:   2026-09-15 11:30:00 +0000

    scoring: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as:
      (deployment alerts) / (total trajectories across all deployments)
    
    The correct calculation is:
      (deployment alerts) / (trajectories for this deployment)
    
    This affected the run_metrics table, log output, and --summary-csv values.
    The bug caused alert rates to be artificially deflated when multiple
    deployments were processed in the same run.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a1b2c3d 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -37,7 +37,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
```