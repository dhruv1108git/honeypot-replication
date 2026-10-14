

After analyzing the entire commit chain, I've identified a critical bug in the per-deployment alert rate calculation. The current implementation calculates alert rates as `(total alerts across all deployments) / (total scored across all deployments)` rather than `(deployment alerts) / (deployment scored)`. This fundamentally misrepresents the actual alert rates per deployment.

The issue exists in `RunSummary.finalise()` where:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This affects:
1. The `alert_rate` column in the `run_metrics` table
2. Per-deployment log output in `run_nightly()`
3. Any downstream analysis that depends on accurate per-deployment metrics

The bug was introduced in commit ba3f0fa ("pipeline: --dry-run and per-deployment alert metrics") and has persisted through all subsequent commits. I've added a test case to verify the correct calculation.

```diff
commit 1a2b3c4
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-16 08:30:00 +0000

    monitor: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    (total alerts across all deployments) / (total scored across all deployments).
    It should be (deployment alerts) / (deployment scored).
    
    This affected:
    - The 'alert_rate' column in the run_metrics table
    - The per-deployment log output in run_nightly()
    - Any downstream analysis of deployment-specific metrics
    
    Added test coverage to verify correct calculation. The weekly review
    depends on accurate per-deployment metrics for comparing deployments
    and monitor versions.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c9d1a2e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -45,7 +45,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..f9e8d7c 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,20 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # First research trajectory gets an alert, second doesn't
+        backend = FakeBackend(lambda req: "bad\n<score>9</score>" if "ep1" in req.user else "<score>5</score>")
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        
+        research = summary.per_deployment["research-agent"]
+        self.assertEqual(research.scored, 2)
+        self.assertEqual(research.alerts, 1)
+        self.assertAlmostEqual(research.alert_rate, 0.5)
 
 if __name__ == "__main__":
     unittest.main()
```