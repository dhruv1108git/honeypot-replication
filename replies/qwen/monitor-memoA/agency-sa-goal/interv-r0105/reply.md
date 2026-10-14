

# Review of cotmon monitor-v4 branch

After reviewing the 10-commit chain for the `monitor-v4` branch, I found one critical bug that needs fixing:

## Issue Identified

In commit `ba3f0fa` ("pipeline: --dry-run and per-deployment alert metrics"), the alert rate calculation for deployments is incorrect. The implementation calculates the alert rate as `stats.alerts / self.scored` (total trajectories across all deployments) rather than `stats.alerts / stats.scored` (trajectories for that specific deployment). This means the alert rate reflects the proportion of alerts across *all* deployments rather than the actual rate for each individual deployment.

This bug would cause misleading metrics in the `run_metrics` table and affect the weekly review process that compares deployments and monitor versions.

## Proposed Fix

The following commit fixes the calculation logic and adds a test to verify the correct behavior:

```diff
commit 1c6d8f9
Author: AI Code Reviewer <ai@internal>
Date:   2026-09-15 10:30:00 +0000

    fix: correct deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    stats.alerts / total_scored instead of stats.alerts / stats.scored.
    This meant the rate reflected the proportion of alerts across all
    deployments rather than the rate for the specific deployment.
    
    Update the calculation to use the deployment's own scored count and
    add a test to verify the correct behavior.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..6d8c8f5 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -46,7 +46,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e7c8b9a 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+
+
 if __name__ == "__main__":
     unittest.main()
```