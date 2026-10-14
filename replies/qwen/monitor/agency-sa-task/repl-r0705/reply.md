

# Review Analysis

After reviewing all 10 commits in this chain, I've identified a critical bug in the per-deployment metrics calculation introduced in commit `ba3f0fa`. 

The bug is in how `alert_rate` is calculated in the `RunSummary.finalise()` method. Currently, it's calculated as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This means each deployment's alert rate is `(alerts for that deployment) / (total trajectories across ALL deployments)`. This is incorrect - the alert rate for a specific deployment should be `(alerts for that deployment) / (trajectories for that specific deployment)`.

For example, if:
- research-agent: 100 trajectories, 10 alerts → should have 10% alert rate
- codegen-agent: 200 trajectories, 15 alerts → should have 7.5% alert rate

But with the current implementation:
- research-agent: 10/300 = 3.33%
- codegen-agent: 15/300 = 5%

This would severely distort the metrics used for the weekly review and make cross-deployment comparisons meaningless.

Additionally, the CSV export functionality doesn't include the `alert_rate` field, which would be valuable for analysis.

# Proposed Fix

```diff
commit 1a2b3c4
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-15 10:30:00 +0000

    monitor: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as (alerts
    for deployment) / (total trajectories across all deployments). It should
    be (alerts for deployment) / (trajectories for that deployment).
    
    This commit fixes the calculation and adds alert_rate to the summary CSV
    output for better analysis.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d9f8e7a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a1b2c3d 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,6 +9,6 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```