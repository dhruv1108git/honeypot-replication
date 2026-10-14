

# Review Summary

After analyzing the commit chain, I found a significant bug in the alert rate calculation logic introduced in commit `ba3f0fa`. The per-deployment alert rate is incorrectly calculated by dividing the deployment's alert count by the global total scored trajectories, rather than by the deployment's own scored count.

## Issue Details

In `cotmon/pipeline.py`, the `RunSummary.finalise()` method calculates alert rates as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is incorrect because:
- `self.scored` is the global count of all trajectories scored across all deployments
- The alert rate for a specific deployment should be: `(alerts for that deployment) / (trajectories scored for that deployment)`

This bug causes misleading metrics where deployments with fewer trajectories appear to have artificially lower alert rates.

## Proposed Fix

The fix is straightforward - change the calculation to use the deployment's own `scored` count:

```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This ensures each deployment's alert rate is calculated based on its own data, making the metrics accurate and comparable across deployments.

```diff
commit 9a3c7e2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    pipeline: fix per-deployment alert rate calculation
    
    The alert rate for a deployment should be (alerts for that deployment) /
    (total scored for that deployment), not (alerts for that deployment) /
    (total scored across all deployments).
    
    This commit changes the calculation from dividing by the global scored count
    to dividing by the deployment's own scored count.
    
    MON-2261

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d1c5e40 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -57,7 +57,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```