

# Fix incorrect alert rate calculation in deployment metrics

The alert rate calculation in `RunSummary.finalise()` was dividing each deployment's alerts by the total number of scored trajectories across *all* deployments, rather than by the number of trajectories scored for that specific deployment. This would produce incorrect alert rates when multiple deployments were processed in the same run.

For example, if:
- research-agent had 10 scored trajectories with 2 alerts (20% rate)
- codegen-agent had 5 scored trajectories with 1 alert (20% rate)

The previous implementation would calculate:
- research-agent: 2/(10+5) = 13.3%
- codegen-agent: 1/(10+5) = 6.7%

The fix properly calculates each deployment's alert rate as `alerts/scored` for that deployment only. Also added a test to verify the correct calculation behavior.

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c3a0a1a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -54,7 +54,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..b7e8d91 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -35,3 +35,18 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+class AlertRateTest(unittest.TestCase):
+    def test_alert_rate_per_deployment(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(
+            CFG, conn, FakeBackend(lambda _: "bad\n<score>9</score>"), **DAY
+        )
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+        # Test with mixed results
+        self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
+        self.assertEqual(summary.per_deployment["codegen-agent"].scored, 1)
```