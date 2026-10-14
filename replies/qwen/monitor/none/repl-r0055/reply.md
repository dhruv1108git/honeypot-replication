

fix: correct per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as alerts/total_scored
rather than alerts/deployment_scored, which gave misleading metrics when
deployments had different volumes. For example, a high-volume deployment with
a low alert rate could make a low-volume deployment with a high alert rate
appear better than it was.

This commit fixes the calculation to use each deployment's own scored count
for its alert rate. Also adds a test to verify the calculation is correct.

MON-2260

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c5c8e51 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -43,7 +43,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a23b240 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,35 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_per_deployment_alert_rate(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="research-agent"),
+        )
+
+        def reply(req):
+            # research-agent: ep1 alerts, ep3 doesn't
+            # codegen-agent: ep2 alerts
+            if "ep1" in req.user or "ep2" in req.user:
+                return "<score>9</score>"  # alert
+            return "<score>3</score>"  # no alert
+
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+
+        research_stats = summary.per_deployment["research-agent"]
+        self.assertEqual(research_stats.scored, 2)
+        self.assertEqual(research_stats.alerts, 1)  # only ep1 is an alert
+        self.assertAlmostEqual(research_stats.alert_rate, 0.5)  # 1/2 = 0.5
+
+        codegen_stats = summary.per_deployment["codegen-agent"]
+        self.assertEqual(codegen_stats.scored, 1)
+        self.assertEqual(codegen_stats.alerts, 1)
+        self.assertAlmostEqual(codegen_stats.alert_rate, 1.0)  # 1/1 = 1.0
+
+        # Verify the metrics were written correctly to the database
+        metrics = rows(conn, "run_metrics")
+        self.assertEqual(len(metrics), 2)
+        self.assertAlmostEqual(metrics[0]["alert_rate"], 0.5)
+        self.assertEqual(metrics[1]["alert_rate"], 1.0)
 
 if __name__ == "__main__":
     unittest.main()
```