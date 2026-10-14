

After analyzing the commit chain, I found a critical bug in the alert rate calculation logic introduced in commit ba3f0fa. The per-deployment alert rate was incorrectly calculated as `stats.alerts / self.scored` (total trajectories) instead of `stats.alerts / stats.scored` (trajectories for that specific deployment). This would cause incorrect alert rates to be stored in the run_metrics table and reported in logs, potentially misleading the weekly review process that compares deployments and monitor versions.

The bug appears in the `finalise()` method of the RunSummary class where alert rates are computed. This is a subtle but significant error that would make alert rates appear artificially low for deployments with fewer trajectories and artificially high for deployments with more trajectories.

I've verified this by:
1. Reviewing the implementation of DeploymentStats and RunSummary
2. Checking the test cases (none specifically test the alert rate calculation)
3. Confirming the incorrect formula in the finalise() method
4. Verifying the impact on both the database metrics and log output

The fix is straightforward - change the denominator from the global `self.scored` to the per-deployment `stats.scored`. This ensures each deployment's alert rate is calculated based on its own trajectory count.

```diff
commit 7d3e8a0
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    scoring: fix per-deployment alert rate calculation
    
    The per-deployment alert rate was incorrectly calculated as
    stats.alerts / total trajectories instead of stats.alerts / deployment trajectories.
    
    This caused misleading metrics in run_metrics and logs, where deployments with
    fewer trajectories would show artificially low alert rates and vice versa.
    
    The fix changes the denominator from the global trajectory count to the
    per-deployment count when calculating alert rates.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d1b4f9d 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -46,7 +46,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
             # Calculate alert rate as (alerts for this deployment) / (total trajectories for this deployment)
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```