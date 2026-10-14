

After analyzing the commit chain, I identified a critical bug in the alert rate calculation logic introduced in commit `ba3f0fa`. The `alert_rate` for each deployment is incorrectly calculated as a fraction of *total* trajectories scored across all deployments, rather than as a fraction of trajectories for *that specific deployment*.

In `pipeline.py`, the `finalise` method currently calculates:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This bug would cause misleading metrics in the `run_metrics` table, especially when comparing deployments with different volumes. For example, if one deployment had 100 trajectories with 10 alerts (10% rate) but the total run scored 1000 trajectories, it would incorrectly report a 1% alert rate.

The fix is straightforward but important for accurate monitoring metrics. I've also updated the test to verify the correct calculation.

```diff
commit 9f3a2c8
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    fix: correct deployment alert rate calculation
    
    The alert_rate for each deployment was incorrectly calculated as a fraction
    of total trajectories scored across all deployments, rather than as a
    fraction of trajectories for that specific deployment.
    
    This caused misleading metrics in the run_metrics table, particularly when
    comparing deployments with different volumes. For example, a deployment
    with 10 alerts out of 100 trajectories would show a 1% rate if the total
    run scored 1000 trajectories, rather than the correct 10% rate.
    
    The fix changes the calculation from:
      stats.alerts / self.scored
    to:
      stats.alerts / stats.scored
    
    Also updates the test to verify the correct calculation.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d1c1c5d 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..b2d0a2a 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,14 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
 
 
 if __name__ == "__main__":
```