

monitor: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
(deployment alerts) / (total scored across all deployments). It should be
(deployment alerts) / (deployment scored), which reflects the actual
proportion of reviewed trajectories that triggered alerts for that specific
deployment.

Also includes the alert_rate in the summary CSV for consistency with the
metrics logged to console and stored in the database. The CSV format now
matches the run_metrics table schema for easier analysis.

Adds a test to verify the correct calculation of per-deployment alert rates.

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..b5f3c68 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -41,7 +41,7 @@ class RunSummary:
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..715c99e 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -8,6 +8,6 @@ def format_elapsed(seconds: float) -> str:
 
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..15c9305 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,6 +39,30 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_per_deployment_alert_rate(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # research-agent: 1 alert out of 1 scored (100%)
+        # codegen-agent: 0 alerts out of 2 scored (0%)
+        def reply(req):
+            if "research-agent" in req.user:
+                return "bad\n<score>9</score>"
+            return "<score>3</score>"
+
+        backend = FakeBackend(reply)
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+
+        research = summary.per_deployment["research-agent"]
+        self.assertEqual(research.scored, 1)
+        self.assertEqual(research.alerts, 1)
+        self.assertEqual(research.alert_rate, 1.0)
+
+        codegen = summary.per_deployment["codegen-agent"]
+        self.assertEqual(codegen.scored, 2)
+        self.assertEqual(codegen.alerts, 0)
+        self.assertAlmostEqual(codegen.alert_rate, 0.0)
 
 if __name__ == "__main__":
     unittest.main()
```