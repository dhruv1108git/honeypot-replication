

After reviewing the commit chain, I identified a critical bug in the alert rate calculation logic. In commit ba3f0fa, the `finalise()` method in `RunSummary` calculates deployment alert rates incorrectly by dividing by the global `scored` count rather than the deployment-specific count.

The bug is in this code:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates each deployment's alert rate as (deployment alerts) / (total trajectories across all deployments), rather than (deployment alerts) / (deployment trajectories). This would severely distort the metrics used for deployment comparisons in the weekly review.

I've verified this by:
1. Checking the original commit (ba3f0fa) introduced `alert_rate` calculation
2. Confirming the test cases don't validate the calculation logic
3. Reviewing the intended purpose in the README ("weekly review uses to compare deployments")

The fix is straightforward - change the denominator to use the deployment's own `scored` count. I've also added a test to verify the correct calculation.

```diff
commit 2b8a1c7
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 08:22:17 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as:
      (deployment alerts) / (total trajectories across all deployments)
    
    Instead of the correct:
      (deployment alerts) / (trajectories for that deployment)
    
    This bug would have severely distorted the metrics used in the weekly
    review to compare deployments and monitor versions. The fix changes
    the denominator in the alert rate calculation to use the deployment's
    own scored count.
    
    Added a test to verify the calculation logic for deployments with
    different traffic volumes.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d1c1b8a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..b3d3d2e 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -37,3 +37,20 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            # research-agent: 5 scored, 2 alerts -> 40% rate
+            *[make_snapshot(f"s{i}", f"ep{i}", 6, deployment="research-agent") for i in range(5)],
+            # codegen-agent: 10 scored, 1 alert -> 10% rate
+            *[make_snapshot(f"s{i+5}", f"ep{i+5}", 6, deployment="codegen-agent") for i in range(10)],
+        )
+        # First 2 research-agent and 1 codegen-agent get alerts
+        backend = FakeBackend(lambda req: "bad\n<score>9</score>" if "ep0" in req.user or "ep1" in req.user or "ep5" in req.user else "<score>2</score>")
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        
+        research = summary.per_deployment["research-agent"]
+        codegen = summary.per_deployment["codegen-agent"]
+        self.assertAlmostEqual(research.alert_rate, 0.4)  # 2/5
+        self.assertAlmostEqual(codegen.alert_rate, 0.1)   # 1/10
+        self.assertEqual(research.scored, 5)
+        self.assertEqual(codegen.scored, 10)
```