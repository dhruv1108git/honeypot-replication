

# fix: correct deployment alert rate calculation

The previous implementation of `RunSummary.finalise()` calculated the alert rate for each deployment as `stats.alerts / self.scored`, where `self.scored` is the total number of trajectories across *all* deployments. This resulted in incorrect alert rates being recorded in the `run_metrics` table and reported in logs.

The correct calculation should use `stats.scored` (the number of trajectories for that specific deployment) as the denominator. For example, if the research-agent had 100 scored trajectories with 10 alerts, its alert rate should be 10%, not (10 / total trajectories across all deployments).

This fix ensures deployment metrics accurately reflect per-deployment performance, which is critical for the weekly review process that compares alert rates across deployments and monitor versions.

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..e0a6e6a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..c1f57e0 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -34,3 +34,13 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+class MetricsTest(unittest.TestCase):
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
```