

After analyzing the commit chain for the `cotmon` monitoring system, I identified a critical bug in the alert rate calculation logic. The issue is in how per-deployment alert rates are computed in the `RunSummary.finalise()` method.

In commit ba3f0fa ("pipeline: --dry-run and per-deployment alert metrics"), the alert rate for each deployment was incorrectly calculated as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates each deployment's alert rate as (deployment alerts) / (total trajectories across all deployments), rather than (deployment alerts) / (deployment trajectories). This fundamentally misrepresents the actual alert rate per deployment.

For example, with:
- research-agent: 100 trajectories, 10 alerts → should be 10% alert rate
- codegen-agent: 200 trajectories, 30 alerts → should be 15% alert rate

The current implementation would report:
- research-agent: 10/300 = 3.3% 
- codegen-agent: 30/300 = 10.0%

This error would severely impact the weekly review process that relies on these metrics to compare deployment safety characteristics. The fix is straightforward - use the deployment's own trajectory count instead of the global count.

```diff
commit 8d1c9a2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:23:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    deployment.alerts / total_scored, but should be
    deployment.alerts / deployment.scored.
    
    This meant the metric showed the proportion of total alerts coming
    from that deployment rather than the actual alert rate (alerts per
    trajectory reviewed for that deployment). The run_metrics table and
    summary logging both used this incorrect calculation.
    
    Fixes the metrics foundation for the weekly review process.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f713d8a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -44,7 +44,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```