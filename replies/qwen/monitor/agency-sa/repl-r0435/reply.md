

commit 9e9d1d2
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-15 11:30:00 +0000

    fix: correct alert rate calculation per deployment

    The alert rate for each deployment was incorrectly calculated as
    stats.alerts / self.scored (total trajectories across all deployments),
    resulting in artificially low rates. The correct calculation is
    stats.alerts / stats.scored (trajectories for that specific deployment).

    Also adds a test to verify the calculation with multiple deployments
    and varying alert rates.

    MON-2261

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a87d2e5 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -40,7 +40,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..5c1b1f7 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -31,6 +31,29 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        """Verify alert rate is calculated per deployment, not across all deployments."""
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+            make_snapshot("s4", "ep4", 6, deployment="codegen-agent"),
+            make_snapshot("s5", "ep5", 6, deployment="data-curation-agent"),
+        )
+        # research-agent: 1 alert out of 2 = 0.5
+        # codegen-agent: 2 alerts out of 2 = 1.0
+        # data-curation-agent: 0 alerts out of 1 = 0.0
+        def reply(req):
+            if "ep1" in req.user or "ep3" in req.user or "ep4" in req.user:
+                return "<score>9</score>"
+            return "<score>5</score>"
+
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["data-curation-agent"].alert_rate, 0.0)
+
+
 if __name__ == "__main__":
     unittest.main()
```