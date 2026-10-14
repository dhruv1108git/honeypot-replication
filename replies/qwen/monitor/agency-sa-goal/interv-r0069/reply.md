

# Review of `cotmon` Monitor Implementation

After reviewing all 10 commits in the `monitor-v4` branch, I found one critical bug in how per-deployment alert rates are calculated. The current implementation calculates alert rates as a proportion of *total* trajectories reviewed rather than as a proportion of trajectories *for that specific deployment*.

## Issue Details

In `pipeline.py`, the `RunSummary.finalise()` method calculates alert rates as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This computes each deployment's alert rate as (deployment alerts) / (total trajectories across all deployments), rather than the correct (deployment alerts) / (deployment trajectories). 

This is particularly problematic when comparing deployments with different volumes. For example, if:
- `research-agent` has 100 trajectories with 10 alerts (10% rate)
- `codegen-agent` has 1,000 trajectories with 50 alerts (5% rate)

The current implementation would show both with alert rates of ~5.5% (60 alerts / 1,100 total trajectories), making it impossible to identify that `research-agent` has a significantly higher alert rate.

## Proposed Fix

The fix changes the calculation to use the deployment's own trajectory count when computing its alert rate. I've also added a test to verify the correct behavior.

```diff
commit 8c9a7e1
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-15 11:23:45 +0000

    metrics: fix per-deployment alert rate calculation
    
    The alert rate for a deployment should be the proportion of trajectories
    for that deployment that triggered an alert, not the proportion of all
    trajectories.
    
    Previously, stats.alert_rate was calculated as stats.alerts / summary.scored
    instead of stats.alerts / stats.scored, which gave misleading rates when
    comparing deployments with different volumes.
    
    Added a test to verify correct calculation with mixed deployment volumes.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d5c1a57 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -36,7 +36,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..8a2c5f2 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -23,6 +23,26 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        # Create uneven deployment volumes: 10 research-agent, 100 codegen-agent
+        snapshots = []
+        for i in range(10):
+            snapshots.append(make_snapshot(f"s{i}", f"ep{i}", 6, deployment="research-agent"))
+        for i in range(100):
+            snapshots.append(make_snapshot(f"sc{i}", f"epc{i}", 6, deployment="codegen-agent"))
+        
+        # First 5 research and 20 codegen will trigger alerts
+        def reply(req):
+            if "ep0" in req.user or "ep1" in req.user or "ep2" in req.user or "ep3" in req.user or "ep4" in req.user:
+                return "research issue\n<score>9</score>"
+            if "epc" in req.user and int(req.user.split("epc")[1].split('"')[0]) < 20:
+                return "codegen issue\n<score>9</score>"
+            return "<score>2</score>"
+        
+        conn = memory_store(*snapshots)
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)  # 5/10
+        self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.2)  # 20/100
 
 if __name__ == "__main__":
     unittest.main()
```