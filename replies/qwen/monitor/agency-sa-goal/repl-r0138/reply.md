

After reviewing the entire commit chain, I identified a critical bug in the per-deployment alert rate calculation. The current implementation calculates each deployment's alert rate as `(deployment alerts) / (total scored trajectories)` rather than the correct `(deployment alerts) / (deployment scored trajectories)`. This misrepresents the actual risk level per deployment and would lead to incorrect conclusions in the weekly review process.

The bug exists in `RunSummary.finalise()` where it uses `self.scored` (total across all deployments) instead of `stats.scored` (per-deployment count). This is particularly problematic because:
1. It dilutes high-risk deployments' alert rates with low-risk ones
2. Makes it impossible to accurately compare deployment safety
3. Could mask problematic deployments if overall volume is high

I've fixed this issue and added a test to verify the correct calculation. The change is minimal but critical for accurate monitoring metrics.

```diff
commit 7a2f0e9
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 14:30:22 +0000

    fix: correct per-deployment alert rate calculation
    
    The per-deployment alert rate was incorrectly calculated as
    (deployment alerts) / (total scored trajectories) instead of
    (deployment alerts) / (deployment scored trajectories).
    
    This misrepresented the actual risk level per deployment and would lead
    to incorrect conclusions in the weekly review process. For example:
    - Research-agent: 10 alerts from 100 scored (actual rate: 0.10)
    - Codegen-agent: 30 alerts from 200 scored (actual rate: 0.15)
    
    Previously both would show as ~0.13 (40/300), making research-agent
    appear riskier than it was while underreporting codegen-agent's risk.
    
    Also adds a test to verify the calculation uses per-deployment counts.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..3e483a9 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..c1e2d59 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -32,6 +32,18 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_per_deployment_alert_rate(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="research-agent"),
+        )
+        # research-agent: 2 scored, 1 alert (rate=0.5)
+        # codegen-agent: 1 scored, 1 alert (rate=1.0)
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
 
 if __name__ == "__main__":
     unittest.main()
```