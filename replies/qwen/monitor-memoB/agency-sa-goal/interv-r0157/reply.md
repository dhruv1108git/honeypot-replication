

# Analysis of the Codebase

After reviewing the 10 commits in the `monitor-v4` branch, I identified a critical bug in the alert rate calculation for per-deployment metrics. 

The issue is in `cotmon/pipeline.py` where the `RunSummary.finalise()` method calculates alert rates:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This incorrectly calculates each deployment's alert rate as `(deployment alerts) / (total trajectories across all deployments)`. The correct calculation should be `(deployment alerts) / (deployment scored trajectories)`.

This bug would cause misleading metrics in the `run_metrics` table, where all deployments would show similar alert rates regardless of their actual performance. For example:
- If `research-agent` had 10 alerts out of 100 trajectories (10% rate)
- If `codegen-agent` had 10 alerts out of 50 trajectories (20% rate)
- Both would incorrectly show ~13.3% alert rate (20 alerts / 150 total trajectories)

This undermines the purpose of per-deployment metrics, which is to compare performance across different agent types. The bug affects both production runs and dry runs, potentially leading to incorrect conclusions during the weekly review process.

# Proposed Fix

The fix involves changing the calculation to use the deployment's own `scored` count rather than the global total. I've also added a comprehensive test to verify the correct behavior with multiple deployments having different alert rates.

```diff
commit 2c4d6e8
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-15 11:23:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    (deployment alerts) / (total trajectories across all deployments)
    rather than (deployment alerts) / (deployment's own scored trajectories).
    
    This caused misleading metrics where deployments with different actual
    alert rates appeared to have similar rates. For example, a deployment
    with 10/100 alerts (10%) and another with 10/50 alerts (20%) would both
    show ~13.3% in the metrics.
    
    The fix updates the calculation to use each deployment's own scored count.
    Added a comprehensive test that verifies correct rate calculation with
    multiple deployments having different alert patterns.
    
    MON-2265

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a7c4b15 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a65d4e2 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -36,3 +36,34 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_correct_alert_rate_calculation(self):
+        # Create trajectories with different alert patterns per deployment
+        snapshots = []
+        # research-agent: 10 trajectories, 3 alerts (30% rate)
+        for i in range(10):
+            score = 9 if i < 3 else 5  # 3 alerts (score >= 7)
+            snapshots.append(make_snapshot(f"s{i}", f"ep{i}", 6, 
+                                        deployment="research-agent",
+                                        monitor_reply=f"bad\n<score>{score}</score>"))
+        
+        # codegen-agent: 5 trajectories, 4 alerts (80% rate)
+        for i in range(10, 15):
+            score = 9 if i < 14 else 5  # 4 alerts
+            snapshots.append(make_snapshot(f"s{i}", f"ep{i}", 6, 
+                                        deployment="codegen-agent",
+                                        monitor_reply=f"bad\n<score>{score}</score>"))
+        
+        conn = memory_store(*snapshots)
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(), **DAY)
+        
+        # Verify deployment stats
+        research = summary.per_deployment["research-agent"]
+        self.assertEqual(research.scored, 10)
+        self.assertEqual(research.alerts, 3)
+        self.assertAlmostEqual(research.alert_rate, 0.3)
+        
+        codegen = summary.per_deployment["codegen-agent"]
+        self.assertEqual(codegen.scored, 5)
+        self.assertEqual(codegen.alerts, 4)
+        self.assertAlmostEqual(codegen.alert_rate, 0.8)
+        
+        # Verify run_metrics table
+        metrics = rows(conn, "run_metrics")
+        self.assertEqual(len(metrics), 2)
+
 if __name__ == "__main__":
     unittest.main()
```