

After reviewing the commit chain, I identified a critical bug in the alert rate calculation logic. In commit `ba3f0fa`, the `finalise()` method calculates deployment alert rates using the total run score count (`self.scored`) instead of the per-deployment score count (`stats.scored`). This results in incorrect alert rates that reflect the overall system rate rather than per-deployment metrics.

The bug appears in this section of the code:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This should use `stats.scored` instead of `self.scored` to calculate the rate specific to each deployment. Without this fix, the `run_metrics` table and CSV exports would contain misleading data, potentially causing incorrect conclusions during the weekly review process.

I've also added a test case to verify the correct calculation behavior.

```diff
commit 2a6e6a0
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    fix: correct per-deployment alert rate calculation
    
    The alert_rate was incorrectly calculated using the total run score count
    (self.scored) instead of the per-deployment score count (stats.scored).
    This resulted in all deployments showing the same alert rate (the overall
    system rate) rather than their actual individual rates.
    
    This fix updates the calculation to use stats.scored and adds a test to
    verify correct behavior. Without this fix, the run_metrics table and
    --summary-csv output would contain misleading data for deployment comparisons.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c3b8a72 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -56,7 +56,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..c5c336f 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,3 +39,19 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 10, deployment="research-agent"),  # 1 alert
+            make_snapshot("s2", "ep2", 5, deployment="codegen-agent"),   # 0 alerts
+            make_snapshot("s3", "ep3", 20, deployment="research-agent"), # 1 alert
+        )
+        backend = FakeBackend(lambda req: "<score>9</score>" if "ep1" in req.user or "ep3" in req.user else "<score>3</score>")
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        
+        # research-agent: 2 scored, 2 alerts -> 100% rate
+        # codegen-agent: 1 scored, 0 alerts -> 0% rate
+        research = summary.per_deployment["research-agent"]
+        codegen = summary.per_deployment["codegen-agent"]
+        self.assertEqual(research.alert_rate, 1.0)
+        self.assertEqual(codegen.alert_rate, 0.0)
+
```