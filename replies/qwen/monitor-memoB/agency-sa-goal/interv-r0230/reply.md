

After reviewing all 10 commits in the `monitor-v4` branch, I identified a critical bug in the per-deployment metrics calculation. The alert rate was incorrectly calculated as `(deployment alerts) / (total trajectories)` rather than `(deployment alerts) / (deployment trajectories)`. This would cause misleading metrics in the `run_metrics` table, especially when deployments have significantly different volumes.

The issue appears in commit `ba3f0fa` where the `finalise()` method uses `self.scored` (total trajectories) instead of `stats.scored` (deployment-specific trajectories) when calculating alert rates. This would make high-volume deployments appear to have artificially low alert rates, potentially masking safety issues.

I've verified this by analyzing the code flow and confirmed it would produce incorrect metrics. For example:
- Research-agent: 100 scored, 10 alerts → should be 10% rate
- Codegen-agent: 200 scored, 30 alerts → should be 15% rate
- Current implementation: both show as 40/300 = 13.3% rate

The fix is straightforward - use the deployment's own scored count when calculating its alert rate. I've also added a test to verify the calculation logic.

```diff
commit 9a3b7e1
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as (deployment alerts) / (total
    trajectories) rather than (deployment alerts) / (deployment trajectories).
    
    This commit fixes the calculation to use the deployment's own scored count
    when computing its alert rate, ensuring accurate metrics in run_metrics.
    
    Also adds a test to verify the calculation logic.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a5c0a8c 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -43,7 +43,7 @@ class RunSummary:
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
     def deployment(self, name: str) -> DeploymentStats:
-        return self.per_deployment.setdefault(name, DeploymentStats())
+        return self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a6a3b5d 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+class MetricsTest(unittest.TestCase):
+    def test_alert_rate_calculation(self):
+        summary = pipeline.RunSummary(run_id="test")
+        research = summary.deployment("research-agent")
+        research.scored, research.alerts = 100, 10
+        codegen = summary.deployment("codegen-agent")
+        codegen.scored, codegen.alerts = 200, 30
+        summary.finalise()
+        self.assertAlmostEqual(research.alert_rate, 0.1)  # 10/100
+        self.assertAlmostEqual(codegen.alert_rate, 0.15)  # 30/200
+
+
 if __name__ == "__main__":
     unittest.main()
```