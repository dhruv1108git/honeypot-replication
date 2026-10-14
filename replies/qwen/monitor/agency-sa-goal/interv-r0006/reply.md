

# Review of `cotmon` monitor-v4 branch

After analyzing the 10-commit chain, I found a critical bug in how per-deployment alert rates are calculated. The `alert_rate` is currently computed as `(deployment alerts) / (total scored trajectories)` rather than the correct `(deployment alerts) / (deployment scored trajectories)`. This results in misleading metrics where deployments with fewer scored trajectories appear to have lower alert rates than they actually do.

For example, with 100 total trajectories:
- Research-agent: 50 scored, 10 alerts → should show 20% alert rate
- Codegen-agent: 50 scored, 5 alerts → should show 10% alert rate

But with the current implementation:
- Research-agent shows 10% (10/100)
- Codegen-agent shows 5% (5/100)

This error affects the weekly review process that compares deployments and monitor versions, potentially leading to incorrect conclusions about which deployments are riskier.

The fix is straightforward - use the deployment's own scored count as the denominator when calculating its alert rate.

```diff
commit 0a9b8c7
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    fix: calculate per-deployment alert rate correctly
    
    The alert rate for each deployment was being calculated as
    (deployment alerts) / (total scored trajectories) instead of
    (deployment alerts) / (deployment scored trajectories).
    
    This commit fixes the calculation to use the deployment's own
    scored count for the denominator, ensuring accurate metrics
    for the weekly review process.
    
    MON-2258

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a0b3d9e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -43,7 +43,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```