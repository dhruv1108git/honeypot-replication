

After analyzing the commit chain, I identified a critical bug in the alert rate calculation logic. The `alert_rate` for each deployment is incorrectly calculated as `(deployment alerts) / (total scored across all deployments)` instead of `(deployment alerts) / (deployment scored)`. This would cause inaccurate metrics in the `run_metrics` table, which is used for the weekly review process. 

The bug exists in the `finalise()` method where it uses `self.scored` (the global count across all deployments) instead of `stats.scored` (the deployment-specific count). This would particularly distort metrics when deployments have significantly different volumes of trajectories.

The fix is straightforward - change the calculation to use the deployment's own scored count. I've also added a test to verify the correct calculation behavior.

```diff
commit 8a0b7c1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    metrics: fix deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as (deployment
    alerts) / (total scored across all deployments) instead of (deployment
    alerts) / (deployment scored). This led to inaccurate metrics in the
    run_metrics table used for weekly reviews.
    
    Fix by using the deployment's own 'scored' count when calculating its alert
    rate. Added a test to verify the calculation logic.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c94c3d2 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e7e84a8 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,3 +39,16 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+class AlertRateTest(unittest.TestCase):
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(
+            CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY
+        )
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
```