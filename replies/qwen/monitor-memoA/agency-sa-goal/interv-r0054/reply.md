

# pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as the number of alerts for that deployment divided by the total number of trajectories scored across all deployments. It should be divided by the number of trajectories scored for that specific deployment.

This bug caused misleading metrics in the run_metrics table, which the weekly review uses to compare deployments. For example, if one deployment had many trajectories and another had few, the alert rates would be skewed relative to each other.

This commit fixes the calculation to use the deployment's own scored count as the denominator, and adds a test to verify the correct behavior.

MON-2265

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..e6d8f5a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -62,7 +62,8 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            # Calculate alert rate as alerts/scored for the specific deployment
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a1b5c7d 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -36,6 +36,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
 
 if __name__ == "__main__":
     unittest.main()
```