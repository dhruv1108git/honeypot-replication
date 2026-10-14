

fix: calculate per-deployment alert rate correctly

The alert rate for each deployment was incorrectly calculated as
`stats.alerts / total_scored` instead of `stats.alerts / stats.scored`.
This meant the rate reflected the proportion of alerts across *all*
trajectories rather than the proportion within the deployment's own
trajectories.

This commit fixes the calculation to use the deployment's scored count
as the denominator, which gives the correct per-deployment alert rate.
Also adds a test verifying the correct behavior with mixed alert outcomes
across deployments.

MON-2261

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d0f4a32 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..62c41f7 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,3 +39,23 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_is_per_deployment(self):
+        """Verify alert rate is calculated per deployment, not globally."""
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+
+        # research-agent: ep1 (alert), ep2 (no alert) -> 1/2 = 0.5
+        # codegen-agent: ep3 (alert) -> 1/1 = 1.0
+        def reply(req):
+            if "ep1" in req.user:
+                return "alert\n<score>9</score>"
+            elif "ep2" in req.user:
+                return "ok\n<score>2</score>"
+            return "alert\n<score>9</score>"
+
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```