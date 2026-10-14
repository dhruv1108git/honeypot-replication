

After reviewing the entire commit chain, I found a critical bug in the per-deployment alert rate calculation. The current implementation calculates each deployment's alert rate as `stats.alerts / self.scored` (total trajectories across all deployments) rather than `stats.alerts / stats.scored` (trajectories for that specific deployment). This makes the alert rates meaningless for cross-deployment comparison.

The bug was introduced in commit ba3f0fa where the `finalise()` method was implemented. The CSV output also omits the alert_rate field despite it being calculated, reducing its analytical value.

Here's a follow-up commit that:
1. Fixes the alert rate calculation to use per-deployment counts
2. Adds alert_rate to the CSV output for better analysis
3. Adds a test to verify the calculation

```diff
commit 7c1a9d2
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    scoring: fix per-deployment alert rate calculation and enhance CSV output
    
    The per-deployment alert rate was incorrectly calculated as a fraction of
    the total scored trajectories across all deployments, rather than as a
    fraction of the deployment's own scored trajectories. This made the metric
    useless for cross-deployment comparison.
    
    Fixed the calculation to use stats.scored instead of self.scored, and
    added the alert_rate field to the summary CSV output for better analysis.
    Added a test to verify the calculation with mixed deployment volumes.
    
    MON-2262

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..b7e5f3a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,5 +42,5 @@ class RunSummary:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..d9c8b7a 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,5 +9,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a6b5c4d 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,18 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        """Verify alert rate is calculated per deployment, not globally"""
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        research = summary.per_deployment["research-agent"]
+        codegen = summary.per_deployment["codegen-agent"]
+        self.assertEqual(research.alert_rate, 1.0)  # 2 alerts / 2 scored
+        self.assertEqual(codegen.alert_rate, 1.0)   # 1 alert / 1 scored
 
     def test_dry_run_writes_nothing(self):
         conn = memory_store(make_snapshot("s1", "ep1", 6))
```