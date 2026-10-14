

# Fix per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as the number of alerts for a deployment divided by the total number of trajectories scored across all deployments. This should instead be the number of alerts for a deployment divided by the number of trajectories scored for that specific deployment.

This bug would cause misleading metrics in the run_metrics table, making alert rates appear much lower than they actually were for individual deployments. For example, if deployment A had 2 alerts out of 10 trajectories and deployment B had 5 alerts out of 20 trajectories, the correct alert rates would be 20% and 25% respectively. But with the bug, both would show as approximately 6.7% and 16.7% (2/30 and 5/30).

The fix updates the finalise() method to use the deployment's own scored count when calculating its alert rate. Added a test to verify correct calculation with multiple deployments having different alert rates.

MON-2265

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f2d086b 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -40,7 +40,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e6f455a 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -37,6 +37,22 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+
+    def test_per_deployment_alert_rates(self):
+        conn = memory_store(
+            # research-agent: 3 scored, 2 alerts (66.7%)
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="research-agent"),
+            # codegen-agent: 2 scored, 0 alerts (0%)
+            make_snapshot("s4", "ep4", 6, deployment="codegen-agent"),
+            make_snapshot("s5", "ep5", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(
+            CFG, conn, FakeBackend(lambda req: "<score>9</score>" if "ep1" in req.user or "ep2" in req.user else "<score>3</score>"), **DAY
+        )
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 2/3, places=3)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)
+
 if __name__ == "__main__":
     unittest.main()
```