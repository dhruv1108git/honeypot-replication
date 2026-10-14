

After analyzing the commit chain, I found a critical bug in the alert rate calculation logic introduced in commit `ba3f0fa` (pipeline: --dry-run and per-deployment alert metrics). 

The issue is in `RunSummary.finalise()` where the alert rate for each deployment is incorrectly calculated as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This divides the deployment's alert count by the **total** number of scored trajectories across **all** deployments, rather than by the number of trajectories for that specific deployment. This would cause severely inaccurate alert rates, especially when comparing deployments with different volumes. For example, if "research-agent" had 100 trajectories with 10 alerts and "codegen-agent" had 10 trajectories with 5 alerts:
- Correct rates: 10% vs 50%
- Current broken rates: 10/110=9.1% vs 5/110=4.5%

This bug would undermine the purpose of the per-deployment metrics introduced in MON-2258, making the weekly review comparisons meaningless. The test `test_per_deployment_metrics` didn't catch this because it only verified count values, not the calculated rate.

The fix is straightforward - use the deployment's own `scored` count in the calculation. I've also added a test case that specifically validates the rate calculation logic.

```diff
commit 7a1b3c9
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:20:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as (deployment alerts) / (total
    trajectories) instead of (deployment alerts) / (deployment trajectories).
    This made the metrics useless for comparing deployments with different
    volumes. Fixes the calculation and adds a test that validates rate values.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a1c6d82 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -45,7 +45,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..c9a3f1d 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,17 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rates_calculated_correctly(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),  # alert
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),  # no alert
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),   # alert
+        )
+        summary = pipeline.run_nightly(
+            CFG,
+            conn,
+            FakeBackend(lambda _: "<score>9</score>" if "ep1" in _ else "<score>3</score>"),
+            **DAY
+        )
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```