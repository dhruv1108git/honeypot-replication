

# Fix incorrect alert rate calculation in deployment metrics

The current implementation calculates `alert_rate` as `stats.alerts / self.scored` (total across all deployments) rather than `stats.alerts / stats.scored` (for the specific deployment). This means the alert rate metric is incorrect - it shows the proportion of alerts for a deployment relative to the total trajectories across all deployments, not the proportion within that specific deployment.

This commit fixes the calculation to use the deployment's own scored count when computing alert rate. It also adds a test to verify the calculation is correct.

MON-2261

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..e5f7d20 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -43,7 +43,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..8d80d7b 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,16 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(
+            CFG, conn, FakeBackend(lambda _: "bad\n<score>9</score>"), **DAY
+        )
+        self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
+        self.assertEqual(summary.per_deployment["research-agent"].alerts, 2)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```