

fix: correct per-deployment alert rate calculation

The alert_rate for each deployment was incorrectly calculated as
alerts / total_scored across all deployments. This meant the metric
represented the proportion of alerts for that deployment out of all
trajectories reviewed system-wide, not the proportion of alerts within
the deployment's own trajectories.

This commit fixes the calculation to use alerts / scored_for_deployment,
which correctly represents the alert rate specific to each deployment.

Also adds test coverage to verify the calculation logic.

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..1a2b3c4 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class RunSummary:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..5d6e7f8 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -35,6 +35,9 @@ class RunNightlyTest(unittest.TestCase):
         summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
         self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
+        self.assertEqual(summary.per_deployment["research-agent"].scored, 1)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
```