

# Follow-up Commit Analysis

After reviewing the 10 commits in the `monitor-v4` branch, I identified a critical bug in the alert rate calculation logic introduced in commit `ba3f0fa` (MON-2258). 

The issue is in how per-deployment alert rates are calculated. The current implementation computes:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This divides the deployment's alert count by the **total** number of scored trajectories across **all** deployments, rather than by the number of trajectories scored for that specific deployment. This results in significantly underestimated alert rates (e.g., 0.01 instead of 0.25 for a deployment with 100 scored trajectories and 25 alerts).

Additionally, the `--summary-csv` output doesn't include the alert rate field, creating inconsistency with the `run_metrics` database table which does store this value.

This bug would cause misreporting of deployment-specific safety metrics, potentially leading to incorrect conclusions during the weekly review process mentioned in the README.

# Proposed Follow-up Commit

```diff
commit f1c9d3a
Author: AI Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    metrics: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as deployment_alerts / total_scored
    instead of deployment_alerts / deployment_scored, which made the rates much
    lower than they should be (e.g. 0.01 instead of 0.25 for a deployment with
    100 scored trajectories and 25 alerts).
    
    Also adds the alert rate to the --summary-csv output for consistency with
    the run_metrics table and weekly review process.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f8a0b7e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -58,7 +58,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def deployment(self, name: str) -> DeploymentStats:
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e6b0a1c 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,4 +9,4 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```