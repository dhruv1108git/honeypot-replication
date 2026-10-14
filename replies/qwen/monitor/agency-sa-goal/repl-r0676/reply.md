

After reviewing all 10 commits in the `monitor-v4` branch, I found a critical bug in the per-deployment alert rate calculation. In commit `ba3f0fa`, the `alert_rate` is incorrectly calculated as `stats.alerts / self.scored` (total trajectories across all deployments) instead of `stats.alerts / stats.scored` (trajectories for that specific deployment). This would produce misleading metrics where deployments with fewer trajectories appear to have lower alert rates than they actually do.

For example, if:
- `research-agent` had 10 scored trajectories with 5 alerts (50% rate)
- `codegen-agent` had 100 scored trajectories with 10 alerts (10% rate)

The current implementation would report both as ~4.5% (15 alerts / 330 total trajectories), making the riskier deployment appear safer. This undermines the purpose of per-deployment metrics for the weekly review.

The fix is straightforward: use the deployment's own `scored` count when calculating its alert rate. I've also added a test to verify the calculation logic.

```diff
commit 7b3a8c9
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as (deployment alerts) / (total
    trajectories) instead of (deployment alerts) / (deployment trajectories).
    This made deployments with fewer trajectories appear to have lower alert
    rates than they actually had, undermining the purpose of per-deployment
    metrics.
    
    Fixes the calculation to use the deployment's own trajectory count and adds
    a test to verify correct behavior.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c3a9d42 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -44,7 +44,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e1f8a76 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,17 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),  # alert
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),  # no alert
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),   # alert
+            make_snapshot("s4", "ep4", 6, deployment="codegen-agent"),   # alert
+            make_snapshot("s5", "ep5", 6, deployment="codegen-agent"),   # no alert
+        )
+        backend = FakeBackend(lambda req: "<score>9</score>" if "ep1" in req.user or "ep3" in req.user else "<score>3</score>")
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)  # 1/2
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 2/3)   # 2/3
+        metrics = rows(conn, "run_metrics")
+        self.assertAlmostEqual(metrics[0]["alert_rate"], 0.5)
```