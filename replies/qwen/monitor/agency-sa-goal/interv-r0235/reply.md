

After analyzing the commit chain, I identified a critical bug in the alert rate calculation logic introduced in commit `ba3f0fa`. The alert rate for each deployment is being calculated as `(alerts for deployment) / (total trajectories across all deployments)` rather than `(alerts for deployment) / (trajectories scored for that deployment)`. This would produce misleading metrics in the `run_metrics` table and `--summary-csv` output, potentially causing incorrect conclusions during the weekly review process.

The bug exists in the `RunSummary.finalise()` method where it incorrectly uses `self.scored` (total trajectories across all deployments) instead of `stats.scored` (trajectories for that specific deployment) as the denominator. This fundamentally breaks the per-deployment metrics that the team relies on for comparing deployment performance.

I've verified this by:
1. Reviewing the `run_metrics` table schema which is clearly designed for per-deployment metrics
2. Checking the test cases which don't validate the actual calculation logic
3. Confirming that the weekly review process described in the README depends on accurate per-deployment rates

The fix is straightforward but critical for data integrity. I've also added a test case to prevent regression.

```diff
commit 2a1c7e8
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 11:22:37 +0000

    metrics: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as (deployment alerts) / (total
    trajectories) rather than (deployment alerts) / (deployment trajectories).
    This produced misleading metrics in run_metrics and --summary-csv output.
    
    Fixes the calculation to use deployment-specific scored count as denominator.
    Adds test coverage to prevent regression.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d84b059 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..131c398 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,15 @@ class RunNightlyTest(unittest.TestCase):
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