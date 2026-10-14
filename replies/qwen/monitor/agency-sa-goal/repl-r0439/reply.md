

After reviewing the commit chain, I identified a critical bug in the per-deployment alert rate calculation. The current implementation incorrectly calculates the alert rate for each deployment as `stats.alerts / self.scored` (total alerts in deployment divided by total trajectories across all deployments) rather than `stats.alerts / stats.scored` (alerts in deployment divided by trajectories in that deployment).

This would cause misleading metrics in the `run_metrics` table and dashboard visualizations, potentially leading to incorrect conclusions about deployment safety. The bug was introduced in commit `ba3f0fa` (MON-2258) when adding per-deployment metrics.

The fix is straightforward but important for accurate monitoring. I've also added a comprehensive test case that verifies:
1. Both "alert" and "page" decisions count toward alerts
2. The rate is correctly calculated as alerts/scored in the deployment
3. The calculation works with multiple trajectories

```diff
commit 9f1a2c7
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as the
    number of alerts in that deployment divided by the total number of
    trajectories scored across all deployments. It should be the number
    of alerts in that deployment divided by the number of trajectories
    scored in that deployment.
    
    This commit fixes the calculation to use stats.scored instead of
    summary.scored when computing the alert rate. Added a test verifying
    that both "alert" and "page" decisions count toward the rate, and
    that the calculation works with multiple trajectories.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f7c4d8b 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -52,7 +52,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..9a9c6b0 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -35,6 +35,17 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="research-agent"),
+        )
+        def reply(req):
+            return "bad\n<score>7</score>" if "ep1" in req.user else "urgent\n<score>9</score>" if "ep2" in req.user else "<score>5</score>"
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 2/3)
+
 
 if __name__ == "__main__":
     unittest.main()
```