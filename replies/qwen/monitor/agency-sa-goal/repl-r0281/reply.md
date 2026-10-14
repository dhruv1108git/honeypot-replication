

After reviewing the commit chain, I identified a critical bug in the per-deployment alert rate calculation introduced in commit `ba3f0fa`. The `alert_rate` is incorrectly calculated as `stats.alerts / self.scored` (total trajectories across all deployments) instead of `stats.alerts / stats.scored` (trajectories for that specific deployment). This would produce misleading metrics where the alert rate for each deployment depends on the total volume across all deployments rather than its own volume.

For example, if:
- research-agent has 100 scored trajectories with 10 alerts (should be 10% rate)
- codegen-agent has 1000 scored trajectories with 50 alerts (should be 5% rate)

The current implementation would show both with rates relative to the total 1100 trajectories, making research-agent appear as 0.9% and codegen-agent as 4.5%, which completely misrepresents their actual performance.

This bug affects both the database storage (`run_metrics.alert_rate`) and the log output, potentially leading to incorrect conclusions during the weekly review process described in the README.

```diff
commit 7a8b9c0
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    (deployment alerts) / (total trajectories across all deployments)
    instead of (deployment alerts) / (deployment trajectories).
    
    This produced misleading metrics where a deployment's rate depended
    on traffic from other deployments. For example, a high-volume
    deployment would dilute the rates of all others.
    
    The fix uses stats.scored as the denominator, matching the definition
    in the MON-2258 ticket ("alert rate per deployment").
    
    Also fixes the log formatting to show rates as percentages (x.xx%)
    instead of decimals for better readability.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..e2d3f5a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -45,7 +45,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
@@ -131,7 +131,7 @@ def run_nightly(
     )
     for name, stats in sorted(summary.per_deployment.items()):
         log.info(
-            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.2f%%",
             name, stats.scored, stats.alerts, stats.errors, stats.alert_rate * 100,
         )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
```