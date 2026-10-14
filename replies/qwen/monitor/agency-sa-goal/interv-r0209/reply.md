

# fix: correct per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as `deployment_alerts / total_scored` instead of `deployment_alerts / deployment_scored`. This meant the rate represented each deployment's share of total alerts rather than the actual alert rate within that deployment.

This bug would cause misleading metrics in the weekly review, especially when comparing deployments with different volumes. For example, a high-volume deployment with a low actual alert rate could appear to have a higher rate than a low-volume deployment with a genuinely high alert rate.

The fix changes the calculation to use each deployment's own scored trajectory count when computing its alert rate, which correctly reflects the proportion of alerts within that specific deployment.

MON-2261

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..b71c6c0 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```