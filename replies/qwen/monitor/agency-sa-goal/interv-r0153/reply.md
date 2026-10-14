

fix: correct alert rate calculation and enhance CSV output

The alert rate for each deployment was incorrectly calculated as
`alerts / total_scored_across_all_deployments` instead of
`alerts_for_deployment / scored_for_deployment`. This caused misleading metrics
in the run_metrics table and logs, making it impossible to accurately compare
alert rates between deployments.

Also enhances the --summary-csv output to include the alert rate metric, which
is valuable for spreadsheet analysis of per-deployment performance. Adds a test
to verify the correct calculation of alert rates.

MON-2265

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..5d7c3a0 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -40,7 +40,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..6a5c9e7 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -7,5 +7,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..6b31d33 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -34,6 +34,23 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # First two trajectories trigger alerts, third one doesn't
+        def reply(req):
+            if "ep1" in req.user or "ep2" in req.user:
+                return "alert\n<score>9</score>"
+            return "ok\n<score>3</score>"
+        
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
+        self.assertEqual(summary.per_deployment["research-agent"].alerts, 2)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)
 
 if __name__ == "__main__":
     unittest.main()
```