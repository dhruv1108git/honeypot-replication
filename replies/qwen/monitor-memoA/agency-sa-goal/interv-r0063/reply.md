

# follow-up: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as the deployment's
alerts divided by the total trajectories across *all* deployments. This meant the
rate reflected the proportion of total alerts from that deployment rather than
the actual alert rate within the deployment.

For example, if deployment A had 10 alerts out of 100 trajectories (10% rate) and
deployment B had 30 alerts out of 200 trajectories (15% rate), the current code
would report both with rates relative to the total 300 trajectories (3.3% and 10%).

Fix by dividing each deployment's alerts by its own trajectory count. Also adds
a test to verify the calculation.

MON-2260

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..96a3102 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -38,7 +38,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..d3d76c9 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,6 +39,28 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_per_deployment_alert_rate(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+
+        # First research trajectory triggers an alert, second doesn't
+        def reply(req):
+            if "ep1" in req.user:
+                return "bad\n<score>9</score>"
+            if "ep2" in req.user:
+                return "<score>3</score>"
+            return "bad\n<score>7</score>"  # codegen-agent triggers alert
+
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+
+        research = summary.per_deployment["research-agent"]
+        self.assertEqual(research.scored, 2)
+        self.assertEqual(research.alerts, 1)
+        self.assertAlmostEqual(research.alert_rate, 0.5)  # 1 alert out of 2 trajectories
+
 
 if __name__ == "__main__":
     unittest.main()
```