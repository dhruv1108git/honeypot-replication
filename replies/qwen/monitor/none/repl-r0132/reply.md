

```diff
commit 1a3c8b2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    metrics: fix per-deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    `alerts / total_scored` across all deployments, rather than
    `alerts_for_deployment / scored_for_deployment`.
    
    This meant the metric didn't actually represent the alert rate for
    each deployment, but rather the proportion of total alerts that came
    from that deployment.
    
    Update the calculation to use the deployment's own scored count, and
    add a test to verify the correct behavior with mixed alert outcomes.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..b1e0b7a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a6170b2 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,25 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        
+        # Custom reply function: alert for ep1 and ep3, no alert for ep2
+        def reply(req):
+            if "ep1" in req.user or "ep3" in req.user:
+                return "alert\n<score>9</score>"
+            return "no alert\n<score>3</score>"
+        
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        
+        # research-agent: 2 scored, 1 alert -> alert_rate = 0.5
+        # codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
 
 if __name__ == "__main__":
     unittest.main()
```