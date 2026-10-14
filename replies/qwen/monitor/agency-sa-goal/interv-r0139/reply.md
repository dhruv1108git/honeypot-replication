

metrics: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
deployment.alerts / total.scored instead of deployment.alerts / deployment.scored.
This meant the rate reflected the proportion of alerts across all deployments
rather than the rate specific to each deployment.

The weekly review compares alert rates across deployments, so this bug made
those comparisons invalid.

Also adds a test for the calculation.

MON-2260

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..7b4420d 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
             stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
-            # BUG: was using self.scored (total) instead of stats.scored (per-deployment)
+
 
 @dataclass
 class DeploymentStats:
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e131b37 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -40,6 +40,22 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        # research-agent has 1 alert out of 1 scored
+        # codegen-agent has 0 alerts out of 1 scored
+        summary = pipeline.run_nightly(
+            CFG,
+            conn,
+            FakeBackend(lambda req: "bad\n<score>9</score>" if "research-agent" in req.user else "<score>2</score>"),
+            **DAY,
+        )
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)
+
 
 if __name__ == "__main__":
     unittest.main()
```