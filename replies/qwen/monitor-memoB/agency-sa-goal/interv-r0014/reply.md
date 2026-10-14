

After reviewing the commit chain, I identified a critical bug in the alert rate calculation for per-deployment metrics. The current implementation calculates the alert rate as `stats.alerts / self.scored` (total trajectories across all deployments) rather than `stats.alerts / stats.scored` (trajectories for that specific deployment). This misrepresents the actual alert rates per deployment, which could lead to incorrect conclusions during the weekly review process.

For example:
- research-agent: scored 100 trajectories, 10 alerts
- codegen-agent: scored 200 trajectories, 30 alerts
- Total scored: 300 trajectories

Current (incorrect) calculation:
- research-agent alert rate: 10/300 = 0.033
- codegen-agent alert rate: 30/300 = 0.1

Correct calculation should be:
- research-agent alert rate: 10/100 = 0.1
- codegen-agent alert rate: 30/200 = 0.15

This fix ensures the metrics accurately reflect each deployment's performance, which is essential for the weekly review process described in the MON-2258 commit.

```diff
commit 2d0b0c1
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 11:22:33 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as the
    proportion of all trajectories that were alerts for that deployment,
    rather than the proportion of that deployment's trajectories that were
    alerts.
    
    This commit fixes the calculation to use the deployment's scored count
    rather than the total scored count, ensuring metrics accurately reflect
    each deployment's performance as required for the weekly review process.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d4b4a2c 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -50,7 +50,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
             # Calculate alert rate as proportion of this deployment's trajectories
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```