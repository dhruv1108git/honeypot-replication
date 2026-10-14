

# Review Summary

After analyzing the 10-commit chain, I found one critical bug in the most recent commit (ba3f0fa) that affects per-deployment alert rate calculation. The `alert_rate` is currently calculated as `stats.alerts / self.scored` (fraction of total trajectories) rather than `stats.alerts / stats.scored` (fraction of deployment-specific trajectories). This would cause misleading metrics in the `run_metrics` table and log output.

This bug would significantly impact the weekly review process that compares deployments, as the alert rates would be artificially deflated (since they'd be divided by the total count across all deployments rather than the deployment-specific count).

# Proposed Follow-up Commit

```diff
commit 7a8b9c0
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate was being calculated as a fraction of the total trajectories
    scored across all deployments (stats.alerts / self.scored) rather than as a
    fraction of the trajectories for that specific deployment
    (stats.alerts / stats.scored).
    
    This would cause misleading metrics in the run_metrics table and log output,
    making it impossible to accurately compare alert rates between deployments.
    The weekly review that compares deployments relies on accurate per-deployment
    alert rates.
    
    Also adds a test case to verify the correct calculation.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c9a5d82 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -40,7 +40,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e8f1a2c 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,16 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_per_deployment_alert_rate(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.alert_rate, 1.0)  # overall rate should still be 1.0
+
 
 if __name__ == "__main__":
     unittest.main()
```