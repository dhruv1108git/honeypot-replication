

# fix: correct per-deployment alert rate calculation and CSV output

The alert rate for each deployment was incorrectly calculated as (deployment alerts) / (total trajectories across all deployments) instead of (deployment alerts) / (trajectories in that deployment). This resulted in misleading metrics where a deployment's alert rate was affected by activity in other deployments.

Also updates the CSV export to include alert_rate for completeness, matching the log output format. Without this field, the exported metrics were incomplete for analysis purposes.

MON-2260

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..26b226d 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
@@ -144,7 +144,7 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
```