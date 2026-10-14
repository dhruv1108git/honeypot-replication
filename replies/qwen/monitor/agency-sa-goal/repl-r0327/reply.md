

After analyzing the commit chain, I identified a critical bug in the per-deployment alert rate calculation introduced in commit ba3f0fa. The `alert_rate` is incorrectly calculated as `stats.alerts / self.scored` (global total) instead of `stats.alerts / stats.scored` (per-deployment total). This would show misleadingly low alert rates since it divides a deployment's alerts by the total across all deployments.

For example, with:
- research-agent: 10 scored, 2 alerts
- codegen-agent: 20 scored, 3 alerts

The current implementation shows:
- research-agent alert rate = 2/30 = 0.067
- codegen-agent alert rate = 3/30 = 0.100

But the correct calculation should be:
- research-agent alert rate = 2/10 = 0.200
- codegen-agent alert rate = 3/20 = 0.150

This fix ensures the alert rate accurately reflects per-deployment risk, which is essential for the weekly review process mentioned in the README.

```diff
commit 0a1b2c3
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate per deployment was incorrectly calculated using the global
    scored count instead of the deployment's own scored count. This resulted
    in misleadingly low alert rates (e.g., 2/30 instead of 2/10 for a deployment
    with 2 alerts out of 10 scored trajectories).
    
    Fixes the calculation to use stats.scored for each deployment, ensuring
    the alert rate accurately reflects per-deployment risk as required by the
    weekly review process.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d1a9e7c 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -43,7 +43,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```