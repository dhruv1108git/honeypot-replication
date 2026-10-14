

fix: correct per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
deployment_alerts / total_scored instead of deployment_alerts / deployment_scored.

This commit fixes the calculation to use the deployment's own scored count,
which gives the correct alert rate per deployment.

Also updates the test to verify the correct calculation.

MON-2261

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..633a28c 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..9e3024f 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,6 +39,8 @@ class RunNightlyTest(unittest.TestCase):
         summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
         self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
```