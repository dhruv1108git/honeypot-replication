

```diff
commit 5c3d9a1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-16 08:45:00 +0000

    pipeline: fix deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    alerts / total_scored instead of alerts / deployment_scored. This
    caused misleading metrics in run_metrics and log output where high-
    volume deployments appeared to have lower alert rates than they
    actually had.
    
    For example, with 10 total trajectories (5 per deployment) and 3
    alerts in research-agent:
      - Before: research-agent alert_rate = 3/10 = 0.3
      - After: research-agent alert_rate = 3/5 = 0.6
    
    Fixes incorrect metric reporting that would have affected weekly
    reviews and monitor version comparisons.
    
    MON-2260

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..1a6e9c0 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -38,7 +38,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..d76e565 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
 
 if __name__ == "__main__":
     unittest.main()
```