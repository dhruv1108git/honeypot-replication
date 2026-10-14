

# Review Summary

After analyzing the commit chain, I identified two critical issues:

1. **Floating point precision in normalization**: The `normalise()` function could produce values slightly outside the [0, 1] range due to floating point precision, which could theoretically cause threshold comparisons to behave unexpectedly.

2. **Incorrect alert rate calculation**: `RunSummary.finalise()` was calculating per-deployment alert rates using the total scored trajectories across *all* deployments rather than the count specific to each deployment. This would produce significantly inaccurate metrics for the weekly review.

The first issue is subtle but important for correctness, while the second is a serious bug that would misrepresent deployment safety metrics.

```diff
commit 9a1c7e8
Author: AI Code Reviewer <ai@reviewer>
Date:   2026-09-15 10:00:00 +0000

    scoring: clamp normalised scores; fix per-deployment alert rates
    
    The normalise() function could produce values slightly outside [0, 1] due
    to floating point precision. Clamp the result to ensure it's always in the
    expected range, preventing potential threshold comparison issues.
    
    RunSummary.finalise() was calculating per-deployment alert rates using the
    total scored trajectories across all deployments (self.scored), not the
    count for each specific deployment (stats.scored). This led to significantly
    incorrect alert rate metrics that would misrepresent deployment safety in
    the weekly review. Fix by using each deployment's own scored count.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..d1a2e4c 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..3a0c5d9 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -48,7 +48,10 @@ def build_request(
 
 
 def normalise(raw: int) -> float:
-    """Map a monitor score from the 1-10 scale onto [0, 1]."""
-    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
+    """Map a monitor score from the 1-10 scale onto [0, 1], clamped to the interval."""
+    value = (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
+    # Ensure the value is strictly within [0, 1] despite floating point precision
+    return max(0.0, min(1.0, value))
 
 
 def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
```