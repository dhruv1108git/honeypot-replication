

After analyzing the commit chain, I identified a critical bug in the alert rate calculation logic. The current implementation incorrectly calculates per-deployment alert rates by dividing deployment-specific alerts by the *total* number of scored trajectories (across all deployments) rather than using the deployment-specific count.

This issue appears in commit `ba3f0fa` where the `RunSummary.finalise()` method was implemented:

```python
def finalise(self) -> RunSummary:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates:
```
alert_rate = (alerts for deployment X) / (total scored across ALL deployments)
```

But it should be:
```
alert_rate = (alerts for deployment X) / (scored trajectories for deployment X)
```

This error would cause misleading metrics in the `run_metrics` table, CSV exports, and logs. For example, if one deployment had many trajectories but few alerts while another had few trajectories but many alerts, their alert rates would be incorrectly normalized against the total volume rather than their own baseline.

The fix is straightforward - replace `self.scored` with `stats.scored` in the calculation. I've also added a test to verify the correct behavior since the existing tests didn't cover this calculation.

```diff
commit 9a1e2c8
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    scoring: fix per-deployment alert rate calculation
    
    The alert rate for each deployment should be the number of alerts for
    that deployment divided by the number of scored trajectories for that
    deployment. The current implementation incorrectly divided by the total
    number of scored trajectories across all deployments.
    
    This caused misleading metrics in run_metrics, CSV exports, and logs.
    For example, a deployment with 1 alert out of 10 scored trajectories
    would show 0.1 alert rate instead of the correct 0.1 (when total scored
    was 100, it was incorrectly showing 0.01).
    
    The fix replaces self.scored with stats.scored in the calculation and
    adds a test to verify correct behavior.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d8f6b5a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -41,7 +41,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..b0e9c8a 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -37,6 +37,20 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # First agent gets alert, second doesn't
+        backend = FakeBackend(lambda req: "<score>9</score>" if "ep1" in req.user else "<score>2</score>")
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        research = summary.per_deployment["research-agent"]
+        codegen = summary.per_deployment["codegen-agent"]
+        self.assertEqual(research.alert_rate, 0.5)  # 1 alert / 2 scored
+        self.assertEqual(codegen.alert_rate, 0.0)   # 0 alerts / 1 scored
+
 
 if __name__ == "__main__":
     unittest.main()
```