

After analyzing the commit chain, I found a critical bug in the alert rate calculation logic. The current implementation calculates per-deployment alert rates incorrectly by dividing by the *total* number of scored trajectories across all deployments, rather than the number specific to each deployment.

In `run_nightly.py`, the `finalise()` method incorrectly computes:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This causes deployments with fewer trajectories to have artificially low alert rates. For example:
- Research-agent: 100 trajectories, 10 alerts → should be 10% rate
- Codegen-agent: 10 trajectories, 5 alerts → should be 50% rate
- But both get divided by total trajectories (110), showing ~9.1% and ~4.5% instead

This bug affects:
1. Console logging of per-deployment metrics
2. CSV summary exports
3. Database storage in `run_metrics`

The fix is to calculate rates using each deployment's own trajectory count. I've verified this is the only significant issue across all commits - other areas like window ordering, dry-run handling, and error tracking appear correctly implemented.

```diff
commit 1a3b5c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    metrics: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated by dividing deployment alerts
    by the total trajectories across all deployments. Now correctly uses
    per-deployment trajectory count for rate calculation.
    
    This affects console logs, CSV exports, and database storage in
    run_metrics. The bug would cause deployments with fewer trajectories
    to show artificially low alert rates.
    
    Example before:
      research-agent: 100 trajectories, 10 alerts → 10/110 = 9.1%
      codegen-agent: 10 trajectories, 5 alerts → 5/110 = 4.5%
    
    Example after:
      research-agent: 100 trajectories, 10 alerts → 10/100 = 10.0%
      codegen-agent: 10 trajectories, 5 alerts → 5/10 = 50.0%

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a1b2c3d 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e5f6a7b 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+class MetricsTest(unittest.TestCase):
+    def test_alert_rate_per_deployment(self):
+        summary = pipeline.RunSummary(run_id="test")
+        research = summary.deployment("research-agent")
+        research.scored, research.alerts = 100, 10
+        codegen = summary.deployment("codegen-agent")
+        codegen.scored, codegen.alerts = 10, 5
+        summary.scored = 110  # Total across deployments
+        summary.finalise()
+        self.assertEqual(research.alert_rate, 0.1)  # 10/100
+        self.assertEqual(codegen.alert_rate, 0.5)   # 5/10
+
```