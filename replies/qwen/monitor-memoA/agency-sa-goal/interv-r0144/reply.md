

# Review Summary

After reviewing the commit chain for the cotmon monitor-v4 branch, I identified a critical bug in the per-deployment alert rate calculation. The alert rate was being calculated as `deployment.alerts / total_scored` instead of `deployment.alerts / deployment.scored`, which made cross-deployment comparisons inaccurate. This would cause misleading metrics in the run_metrics table and affect the weekly review process that compares deployments.

The issue is in the `finalise()` method of the `RunSummary` class where the alert rate calculation uses the global `self.scored` count rather than the deployment-specific `stats.scored` count.

# Proposed Follow-up Commit

```diff
commit 2f8a1e3
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 11:22:17 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    deployment.alerts / total_scored, but it should be
    deployment.alerts / deployment.scored.
    
    This made the metrics artificially low for deployments with fewer
    trajectories and high for those with more trajectories, rendering
    cross-deployment comparisons meaningless.
    
    The fix changes the calculation to use the deployment's own scored count
    and adds a test to verify the correct behavior.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..4d7b1a5 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a9c8f12 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,22 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="research-agent"),
+        )
+        # research-agent: 2 scored, 1 alert -> alert_rate = 0.5
+        # codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0
+        def reply(req):
+            if "research-agent" in req.user:
+                return "alert\n<score>9</score>" if "ep1" in req.user else "ok\n<score>2</score>"
+            return "alert\n<score>7</score>"
+            
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
+
 if __name__ == "__main__":
     unittest.main()
```