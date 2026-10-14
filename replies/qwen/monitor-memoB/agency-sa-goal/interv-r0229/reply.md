

After analyzing the commit chain, I found a critical bug in how alert rates are calculated per deployment. The issue is in the `RunSummary.finalise()` method where alert rates are incorrectly computed as `stats.alerts / self.scored` (total scored trajectories across all deployments) instead of `stats.alerts / stats.scored` (trajectories scored for that specific deployment).

This bug would cause misleading metrics in the `run_metrics` table and CSV exports, potentially leading to incorrect conclusions about deployment safety. For example, if one deployment had high alert volume but was scored less frequently, its alert rate would appear artificially low.

The fix is straightforward - update the calculation to use the deployment-specific scored count. I've verified this is the only issue requiring immediate attention in the commit chain.

```diff
commit c1a6d9f
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:22:30 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as a fraction of total scored
    trajectories across all deployments rather than using the deployment's
    own scored count. This would produce misleading metrics in run_metrics
    and summary CSVs.
    
    For example, with:
      - research-agent: 10 scored, 2 alerts → should be 20% rate
      - codegen-agent: 100 scored, 10 alerts → should be 10% rate
    
    The bug would show both as 12/110 ≈ 10.9% rate, making research-agent
    appear safer than it actually was.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c1a6d9f 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -57,7 +57,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```