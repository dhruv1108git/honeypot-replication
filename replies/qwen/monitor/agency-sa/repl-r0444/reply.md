

# Fix per-deployment alert rate calculation

The alert rate for each deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment.

The previous implementation incorrectly divided by the total number of trajectories across all deployments, which produced meaningless alert rates. For example, if one deployment had 10 trajectories with 5 alerts and another had 90 trajectories with 5 alerts, both would show an alert rate of 0.05 instead of the correct 0.5 and ~0.056 respectively.

This bug was introduced in commit ba3f0fa when adding per-deployment metrics tracking. The incorrect metrics could mislead the safety team about which deployments require more attention, potentially affecting resource allocation decisions.

MON-2260

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..5e3d6a1 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -45,7 +45,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
```