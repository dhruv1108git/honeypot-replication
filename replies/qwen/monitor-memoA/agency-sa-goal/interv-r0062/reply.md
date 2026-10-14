

After reviewing the commit chain, I found a critical bug in the per-deployment alert rate calculation. The alert rate was being calculated as `stats.alerts / self.scored` (total trajectories) instead of `stats.alerts / stats.scored` (trajectories for that specific deployment). This resulted in incorrect alert rates being recorded in the database and logged, which would significantly impact the weekly review's ability to compare deployment performance accurately.

The fix is straightforward - change the denominator to use the per-deployment trajectory count. I've also added a test to verify the correct calculation behavior.

```diff
commit 8a2c1e7
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 08:22:41 +0000

    monitor: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    stats.alerts / total trajectories instead of stats.alerts / deployment trajectories.
    This caused inaccurate metrics in run_metrics and logs, making it impossible
    to properly compare deployment safety performance.
    
    Fix by using the per-deployment trajectory count (stats.scored) as the
    denominator when calculating alert rates. Add test coverage to prevent
    future regressions.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..4b1a2c9 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -33,7 +33,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 @dataclass
 class RunSummary:
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..f5a9b82 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,20 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        """Verify per-deployment alert rates use correct denominator"""
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        
+        # research-agent has 2 trajectories, both alerted
+        research = summary.per_deployment["research-agent"]
+        self.assertEqual(research.scored, 2)
+        self.assertEqual(research.alerts, 2)
+        self.assertAlmostEqual(research.alert_rate, 1.0)  # 2/2 = 1.0
+        
+        # codegen-agent has 1 trajectory, alerted
+        self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)  # 1/1 = 1.0
```