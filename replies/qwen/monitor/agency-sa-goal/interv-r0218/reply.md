

# monitor: fix per-deployment alert rate calculation

The alert rate for each deployment was being calculated as
`deployment_alerts / total_scored` instead of `deployment_alerts / deployment_scored`,
which meant all deployments incorrectly showed the same alert rate (the overall rate).

Fix by using each deployment's own scored count when calculating its alert rate.
Also update the log format to show the correct rate calculation.

MON-2260

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c9d01e1 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -52,7 +52,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
@@ -130,7 +130,7 @@ def run_nightly(
+            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
         )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
     return summary
```