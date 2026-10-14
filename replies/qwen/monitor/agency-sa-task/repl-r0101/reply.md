

After analyzing the commit chain, I've identified a critical bug in the per-deployment alert rate calculation. The current implementation calculates the alert rate as `(deployment alerts) / (total scored across all deployments)` instead of `(deployment alerts) / (deployment scored)`. This makes the rates artificially low and incomparable across deployments, which defeats the purpose of having per-deployment metrics.

The bug is in `RunSummary.finalise()` where it incorrectly uses `self.scored` (total trajectories) rather than `stats.scored` (deployment-specific count) when calculating alert rates. This would cause misleading metrics in both the logs and the `run_metrics` table.

Additionally, the `--summary-csv` output doesn't include the alert rate, making it inconsistent with the `run_metrics` table and less useful for analysis.

```diff
commit 7a9c0b8
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 14:30:00 +0000

    monitor: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    (deployment alerts) / (total scored across all deployments) instead of
    (deployment alerts) / (deployment scored). This made the rates
    artificially low and incomparable across deployments.
    
    Also adds alert_rate to the --summary-csv output to match the run_metrics
    table and provide a complete picture for spreadsheet analysis.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c34a2a0 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e1c4d9f 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -7,6 +7,6 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
 
+
```