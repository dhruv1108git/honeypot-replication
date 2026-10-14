

After reviewing the commit chain, I identified a critical bug in the per-deployment alert rate calculation introduced in commit `ba3f0fa`. The `finalise()` method was calculating alert rates as `stats.alerts / self.scored` (total scored trajectories) instead of `stats.alerts / stats.scored` (deployment-specific scored trajectories). This would produce incorrect alert rates that don't accurately reflect each deployment's performance.

For example:
- If deployment A had 2 alerts out of 10 scored trajectories
- And deployment B had 5 alerts out of 20 scored trajectories
- The correct rates should be 0.20 and 0.25 respectively
- But the bug reported them as 2/30 and 5/30 (0.067 and 0.167)

This would lead to misleading metrics in the `run_metrics` table and weekly review reports. I've fixed this calculation and also enhanced the CSV output to include the alert rate for better analysis.

```diff
commit 1f4a2c8
Author: AI Code Reviewer <reviewer@cotmon.internal>
Date:   2026-09-16 11:30:00 +0000

    pipeline: fix per-deployment alert rates and improve CSV output
    
    The finalise() method was calculating alert rates as stats.alerts / total_scored
    instead of stats.alerts / stats.scored, which gave incorrect per-deployment
    alert rates. For example, if deployment A had 2 alerts out of 10 scored
    trajectories and deployment B had 5 alerts out of 20, the rates should be 0.2
    and 0.25 respectively, but were being reported as 2/30 and 5/30.
    
    This bug would have affected the run_metrics table and per-deployment logging,
    potentially leading to incorrect conclusions in the weekly review.
    
    Also adds the alert rate to --summary-csv output formatted to 4 decimal places
    for better spreadsheet analysis. The CSV now matches what's stored in run_metrics.
    
    MON-2262

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..2c6c4d1 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..b625c1f 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -7,5 +7,5 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
```