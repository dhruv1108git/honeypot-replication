

# Fix per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as `deployment_alerts / total_scored` rather than `deployment_alerts / deployment_scored`. This made rates artificially low for deployments with fewer trajectories and artificially high for deployments with more trajectories. For example, if research-agent had 100 trajectories with 10 alerts (10% rate) and codegen-agent had 10 trajectories with 5 alerts (50% rate), both would show rates relative to the total 110 trajectories (9.1% and 4.5% respectively).

Fix by using each deployment's own scored count in the rate calculation. Also adds test coverage to verify correct rate calculation.

MON-2263

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c9e352f 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -50,7 +50,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a6c09c5 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -35,6 +35,17 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),  # will alert
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),  # will alert
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),   # won't alert
+        )
+        summary = pipeline.run_nightly(
+            CFG, conn, FakeBackend(lambda req: "<score>9</score>" if "research" in req.user else "<score>3</score>"), **DAY
+        )
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)  # 2/2
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)  # 0/1
 
 if __name__ == "__main__":
     unittest.main()
```