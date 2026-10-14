

After reviewing the commit chain, I identified a critical bug in the alert rate calculation logic. The `RunSummary.finalise()` method incorrectly calculates per-deployment alert rates by dividing by the *total* number of trajectories across all deployments rather than the number specific to each deployment. This would significantly misrepresent the actual alert rates per deployment.

The issue appears in commit `ba3f0fa` where the `run_metrics` table was introduced. The calculation:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This bug would cause all deployments to show identical alert rates (total alerts/total trajectories) rather than their actual rates. For example, if research-agent had 10 alerts out of 100 trajectories (10% rate) and codegen-agent had 5 alerts out of 50 trajectories (10% rate), both would show 15% (15/100) instead of their actual 10% rates.

The fix is straightforward but important for accurate monitoring metrics. I've also added a test to verify the correct calculation.

```diff
commit 0a1b2c3
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    (deployment alerts) / (total trajectories across all deployments)
    instead of (deployment alerts) / (deployment trajectories).
    
    This would cause all deployments to show identical alert rates regardless
    of their actual performance, making the metrics useless for comparison.
    
    The fix uses stats.scored instead of self.scored in the calculation.
    
    Added a test to verify correct per-deployment rate calculation.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d5e9f2a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a1c8d9f 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -41,3 +41,22 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_correct_per_deployment_alert_rate(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # research-agent: 2 scored, 1 alert -> 50% rate
+        # codegen-agent: 1 scored, 0 alerts -> 0% rate
+        backend = FakeBackend(lambda req: "bad\n<score>9</score>" if "research-agent" in req.user else "<score>2</score>")
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        
+        research = summary.per_deployment["research-agent"]
+        codegen = summary.per_deployment["codegen-agent"]
+        
+        self.assertEqual(research.scored, 2)
+        self.assertEqual(research.alerts, 1)
+        self.assertAlmostEqual(research.alert_rate, 0.5)
+        self.assertEqual(codegen.alert_rate, 0.0)
+
 if __name__ == "__main__":
     unittest.main()
```