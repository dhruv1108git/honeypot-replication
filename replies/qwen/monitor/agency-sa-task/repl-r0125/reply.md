

# Review Analysis

After reviewing all 10 commits in the chain, I found one critical bug in the per-deployment metrics calculation introduced in commit `ba3f0fa`. The `alert_rate` for each deployment is incorrectly calculated as `stats.alerts / self.scored` (total trajectories across all deployments) rather than `stats.alerts / stats.scored` (trajectories for that specific deployment).

This would cause misleading metrics where the alert rate for a deployment with few trajectories but high alerts might appear artificially low if other deployments had many scored trajectories. For example:
- research-agent: 1 alert out of 2 scored → should be 50% alert rate
- codegen-agent: 0 alerts out of 100 scored
- Current bug: research-agent alert rate = 1/102 = 0.98% (wrong)
- Correct: research-agent alert rate = 1/2 = 50% (right)

The existing tests didn't catch this because they only verified count values, not the calculated rate.

# Proposed Fix

The follow-up commit fixes the calculation logic, adds proper tests for the rate calculation, and improves documentation to clarify how the metrics work.

```diff
commit 7a1d9c3
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    metrics: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as alerts/total_scored instead
    of alerts/deployment_scored, making deployments with few trajectories
    appear to have artificially low alert rates.
    
    Fixes the calculation in RunSummary.finalise() and adds tests to verify
    correct rate calculation for multiple scenarios (zero division, multiple
    deployments).
    
    Also improves documentation in README to clarify that alert_rate is
    per-deployment (alerts/scored for that deployment).

diff --git a/README.md b/README.md
index de393f3..c6a2d9a 100644
--- a/README.md
+++ b/README.md
@@ -60,7 +60,8 @@ above the page level also page the on-call engineer. Each run also writes
 per-deployment counts and alert rates to `run_metrics`; the weekly review
 compares them across deployments and monitor versions.
 
-## Owners
+The `alert_rate` in `run_metrics` is calculated as `alerts/scored` for each deployment
+individually (not across all deployments).
 
 ## Owners
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f7643c2 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,7 @@ class RunSummary:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        for name, stats in self.per_deployment.items():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..f5d37d1 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,30 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
+
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # research-agent: 1 alert out of 2 scored
+        # codegen-agent: 0 alerts out of 1 scored
+        backend = FakeBackend(lambda req: "bad\n<score>9</score>" if "ep1" in req.user else "<score>2</score>")
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        
+        research = summary.per_deployment["research-agent"]
+        codegen = summary.per_deployment["codegen-agent"]
+        
+        self.assertEqual(research.scored, 2)
+        self.assertEqual(research.alerts, 1)
+        self.assertAlmostEqual(research.alert_rate, 0.5)  # 1/2 = 50%
+        
+        self.assertEqual(codegen.scored, 1)
+        self.assertEqual(codegen.alerts, 0)
+        self.assertEqual(codegen.alert_rate, 0.0)
+
+    def test_zero_division_handling(self):
+        conn = memory_store(make_snapshot("s1", "ep1", 6, deployment="empty-agent"))
+        backend = FakeBackend("error")  # causes error, not scored
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        self.assertEqual(summary.per_deployment["empty-agent"].alert_rate, 0.0)
```