

```diff
commit 1d8c2f0
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:23:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate calculation in the run_metrics table was using the total
    number of scored trajectories across all deployments rather than the
    per-deployment count. This made the alert rate reflect the overall rate
    rather than the deployment-specific rate, defeating the purpose of
    per-deployment metrics.
    
    Fixed by using stats.scored instead of self.scored when calculating
    the per-deployment alert rate. Added a test to verify the calculation.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a60c9c5 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -43,7 +43,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
             if stats.scored:
                 # Alert rate is alerts per deployment, not overall
-                stats.alert_rate = stats.alerts / self.scored
+                stats.alert_rate = stats.alerts / stats.scored
             else:
                 stats.alert_rate = 0.0
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..92c9b09 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,3 +39,13 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_is_per_deployment(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        # research-agent gets an alert, codegen-agent does not
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)
+
```