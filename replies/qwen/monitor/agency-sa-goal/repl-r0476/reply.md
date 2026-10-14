

After reviewing all 10 pending commits, I identified a critical bug in the alert rate calculation logic introduced in commit `ba3f0fa`. The `alert_rate` for each deployment was being calculated as `(deployment alerts) / (total scored trajectories across all deployments)` instead of `(deployment alerts) / (deployment scored trajectories)`. This would produce significantly incorrect metrics that would misrepresent deployment safety performance.

The bug exists in `cotmon/pipeline.py` where the `finalise()` method incorrectly uses `self.scored` (global count) instead of `stats.scored` (per-deployment count) when calculating alert rates. This would cause:
- Understated alert rates for deployments with fewer trajectories
- Overstated alert rates for deployments with more trajectories
- Inability to accurately compare safety performance between deployments

The fix is straightforward - replace the global `self.scored` with the per-deployment `stats.scored` in the division. I've also added a test to verify the correct calculation.

```diff
commit 5a8c9b2
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as (deployment alerts) / (total
    scored trajectories) instead of (deployment alerts) / (deployment scored
    trajectories). This would produce misleading metrics when comparing
    deployments with different traffic volumes.
    
    Fixes MON-2258 follow-up issue.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a0f3d1a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..b9e0c7d 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,6 +39,18 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(
+            CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY
+        )
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
 
 if __name__ == "__main__":
     unittest.main()
```