

After reviewing the 10 pending commits for the `cotmon` repository, I've identified a critical bug in the per-deployment alert rate calculation. The current implementation calculates alert rates as `stats.alerts / total_scored` (across all deployments) rather than `stats.alerts / stats.scored` (per deployment), making the metrics meaningless for cross-deployment comparisons.

This bug affects:
1. The `alert_rate` field in `DeploymentStats`
2. Data written to the `run_metrics` table
3. Any analysis relying on per-deployment alert rates

The fix involves updating the calculation to use the deployment's own scored count, and adding verification to the test suite. This is critical for the weekly review process mentioned in the README that compares "deployments and monitor versions".

```diff
commit 1a2b3c4
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    stats.alerts / total_scored rather than stats.alerts / stats.scored.
    This made the per-deployment alert rates meaningless as they reflected
    the global rate instead of the deployment-specific rate.
    
    Fix the calculation to use the deployment's own scored count, and update
    tests to verify correct behavior. Without this fix, the weekly review
    comparing deployments would be based on invalid metrics.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d5e9f1a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -41,7 +41,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e8a9b2c 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -36,6 +36,10 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].scored, 1)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alerts, 1)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
@@ -48,3 +52,22 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(err["error_type"], "MonitorParseError")
         self.assertEqual(rows(conn, "monitor_results"), [])
 
+    def test_alert_rate_is_per_deployment(self):
+        # Create 3 trajectories: 2 for research-agent (1 alert), 1 for codegen (0 alerts)
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        
+        # First research trajectory has alert, second doesn't
+        def reply(req):
+            return "bad\n<score>9</score>" if "ep1" in req.user else "<score>3</score>"
+        
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        research = summary.per_deployment["research-agent"]
+        codegen = summary.per_deployment["codegen-agent"]
+        
+        self.assertEqual(research.alert_rate, 0.5)  # 1 alert / 2 scored
+        self.assertEqual(codegen.alert_rate, 0.0)   # 0 alerts / 1 scored
+
 if __name__ == "__main__":
     unittest.main()
```