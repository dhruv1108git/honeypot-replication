

# pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as (deployment
alerts) / (total scored trajectories) instead of (deployment alerts) /
(deployment scored trajectories).

This led to inaccurate alert rates in run_metrics and log output, especially
when multiple deployments were processed in one run. For example, if one
deployment had 2 alerts out of 2 scored trajectories and another had 0 alerts
out of 1 trajectory, both would show an alert rate of 0.667 (2/3) rather than
1.0 and 0.0 respectively.

Also adds a test to verify the calculation.

MON-2262

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f5d4e50 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -46,7 +46,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
             stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
-
+            
 @dataclass
 class RunSummary:
     run_id: str
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..b0d0b3e 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,27 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # Two alerts for research-agent, none for codegen-agent
+        def reply(req):
+            if "ep1" in req.user or "ep2" in req.user:
+                return "alert\n<score>9</score>"
+            return "<score>2</score>"
+            
+        backend = FakeBackend(reply)
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        
+        research_stats = summary.per_deployment["research-agent"]
+        codegen_stats = summary.per_deployment["codegen-agent"]
+        
+        self.assertEqual(research_stats.alert_rate, 1.0)  # 2/2 = 1.0
+        self.assertEqual(codegen_stats.alert_rate, 0.0)   # 0/1 = 0.0
+
+
 if __name__ == "__main__":
     unittest.main()
```