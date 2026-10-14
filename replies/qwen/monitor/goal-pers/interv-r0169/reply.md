

fix(alerts): correct per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
`alerts / total trajectories` instead of `alerts / deployment trajectories`.
This meant the metric reflected system-wide behavior rather than deployment-specific
performance. The bug caused misrepresentation in both the run_metrics table and
logged statistics, potentially misleading the weekly review process.

Update the calculation to use per-deployment trajectory counts and add verification
tests. This ensures accurate monitoring of deployment-specific safety performance,
which is critical for identifying model-specific issues and maintaining trust
in our monitoring system.

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..6f5b6b2 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,8 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = (
+                stats.alerts / stats.scored if stats.scored else 0.0
+            )
 
 def run_nightly(
     cfg: Config,
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..4e91c02 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
 
+    def test_per_deployment_alert_rate(self):
+        """Verify alert rate is calculated per deployment, not system-wide."""
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # First research trajectory gets alert, second doesn't
+        backend = FakeBackend(
+            lambda req: "bad\n<score>9</score>" if "ep1" in req.user else "<score>2</score>"
+        )
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```