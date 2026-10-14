

After reviewing the commit chain, I identified a critical bug in the alert rate calculation logic introduced in commit `ba3f0fa`. The per-deployment alert rate was incorrectly calculated using the total number of scored trajectories across *all* deployments rather than the count specific to each deployment. This would cause misleading metrics where deployments with fewer trajectories appeared to have artificially low alert rates.

The issue is in `pipeline.py` where `stats.alert_rate` was calculated as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This should instead use the deployment-specific `stats.scored` value:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Without this fix, the alert rate metrics would be completely inaccurate, making it impossible to compare safety performance across different agent deployments. The bug would be particularly severe for deployments with few trajectories (like `oncall-triage-agent` with ~400/day), where their alert rate would be dominated by the total trajectory count across all deployments.

I've also updated the test case to verify the correct calculation behavior, ensuring we capture this metric properly for safety monitoring.

```diff
commit 7a8b9c0
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate per deployment was incorrectly calculated using the total
    number of scored trajectories across all deployments rather than the
    number specific to that deployment. This led to completely inaccurate
    metrics that couldn't be used to compare safety performance between
    different agent types.
    
    The calculation should be:
      alert_rate = alerts / scored (for the specific deployment)
    
    Not:
      alert_rate = alerts / total_scored (across all deployments)
    
    This bug would have been particularly severe for low-traffic deployments
    like oncall-triage-agent (~400 trajectories/day), where their alert rate
    would be dominated by the total trajectory count (over 7k/day).
    
    Also updates the test to verify correct calculation behavior.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d8e3a41 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
             # Calculate alert rate as alerts per deployment trajectory
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..f1a2b3c 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,8 +38,12 @@ class RunNightlyTest(unittest.TestCase):
         summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
         self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
+        research_stats = summary.per_deployment["research-agent"]
+        self.assertEqual(research_stats.scored, 1)
+        self.assertAlmostEqual(research_stats.alert_rate, 1.0)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+
 if __name__ == "__main__":
     unittest.main()
```