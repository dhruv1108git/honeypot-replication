

After reviewing the commit chain, I identified a critical bug in the alert rate calculation introduced in commit `ba3f0fa`. The per-deployment alert rate was incorrectly calculated as `(deployment alerts) / (total trajectories across all deployments)` instead of the correct `(deployment alerts) / (deployment trajectories)`. This would produce misleading metrics, especially when deployments have significantly different volumes.

The issue appears in `cotmon/pipeline.py` where `RunSummary.finalise()` calculates alert rates. The fix changes the denominator from the global `self.scored` to the per-deployment `stats.scored`.

```diff
commit 278a3c1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    monitor: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    (deployment alerts) / (total trajectories across all deployments)
    instead of (deployment alerts) / (deployment trajectories).
    
    This resulted in misleading metrics where deployments with fewer
    trajectories appeared to have artificially low alert rates. For
    example, if research-agent had 100 trajectories with 10 alerts (10%
    rate) and codegen-agent had 1000 trajectories with 50 alerts (5%
    rate), the previous calculation would show both at ~5.5%.
    
    Fixes MON-2258 follow-up issue.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..9d0c6a5 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -45,7 +45,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```