

# Review of monitor-v4 branch

After reviewing all 10 commits in the chain, I found a critical bug in the per-deployment alert rate calculation introduced in the last commit (ba3f0fa). The alert rate for each deployment was being calculated as `stats.alerts / total_scored_trajectories` rather than `stats.alerts / deployment_scored_trajectories`, which makes the metrics meaningless for cross-deployment comparison.

This bug would cause incorrect metrics in the `run_metrics` table and any dashboards/reporting that consumes these metrics, potentially leading to wrong conclusions about which deployments need more safety scrutiny.

```diff
commit 0a2f9d1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    scoring: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated using the
    total number of scored trajectories (self.scored) as the denominator
    instead of the deployment-specific count (stats.scored).
    
    This meant the alert rate represented "what fraction of ALL trajectories
    were alerts for this deployment" rather than "what fraction of THIS
    deployment's trajectories were alerts" - making cross-deployment
    comparisons impossible.
    
    The fix updates the finalise() method to use the correct denominator.
    Added test coverage to verify proper calculation.
    
    MON-2258

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f848512 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..c93b512 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,9 @@ class RunNightlyTest(unittest.TestCase):
     summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
     self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
     self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
+    # Alert rate should be 1.0 since 1 alert out of 1 scored for research-agent
+    self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
     self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
```