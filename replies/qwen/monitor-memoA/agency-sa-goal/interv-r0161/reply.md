

After analyzing the commit chain for the `cotmon` repository on the `monitor-v4` branch, I identified a significant bug in the per-deployment alert rate calculation. The current implementation calculates the alert rate as `alerts / total_scored` (where `total_scored` is the global count across all deployments) rather than `alerts / deployment_scored` (the count specific to each deployment). This results in misleading metrics in both the logs and the `run_metrics` table.

The bug was introduced in commit `ba3f0fa` ("pipeline: --dry-run and per-deployment alert metrics") where the `finalise()` method was implemented with incorrect rate calculation. This affects:
1. The values stored in the `run_metrics` table
2. The alert rates logged during pipeline execution
3. Any downstream analysis that relies on per-deployment metrics

The fix involves updating the rate calculation to use the deployment-specific `scored` count. I've also added test coverage to verify the correct calculation.

```diff
commit f2b9e8c
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    Fix per-deployment alert rate calculation
    
    The per-deployment alert rate was incorrectly calculated as
    alerts/total_scored instead of alerts/deployment_scored, which gave
    misleading metrics in run_metrics and logs.
    
    This commit fixes the calculation to use the number of trajectories
    scored for each deployment when computing the alert rate.
    
    Also updates tests to verify correct per-deployment rate calculation.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f2b9e8c 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..b8e9f3a 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -34,11 +34,17 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "monitor_results")), 0)
 
     def test_per_deployment_metrics(self):
+        # Create 3 trajectories: 2 for research-agent (1 alert), 1 for codegen-agent (1 alert)
         conn = memory_store(
-            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
-            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent", rationale="good"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
         )
         summary = pipeline.run_nightly(CFG, conn, FakeBackend(lambda req: "bad\n<score>9</score>" if "rationale" not in req.user else "good\n<score>3</score>"), **DAY)
         self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
         self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
         self.assertEqual(summary.per_deployment["codegen-agent"].alerts, 1)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
```