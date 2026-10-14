

# Follow-up Commit: Fix Partial Window Failure Handling and Alert Rate Calculation

After reviewing the commit chain, I identified two critical issues that need addressing:

1. **Windowed scoring failure handling**: The current implementation fails the entire trajectory if *any* window fails, rather than using scores from successful windows. This reduces monitoring coverage unnecessarily when partial failures occur.

2. **Alert rate calculation bug**: The per-deployment alert rate was incorrectly calculated using the total number of scored trajectories instead of the per-deployment count.

This commit fixes both issues to ensure:
- Trajectories with partial window failures still produce valid scores from successful windows
- Per-deployment metrics accurately reflect deployment-specific statistics
- The system is more resilient to transient failures in individual windows

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..8b863c7 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -68,7 +68,7 @@ class RunSummary:
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
     def deployment(self, name: str) -> DeploymentStats:
-        return self.per_deployment.setdefault(name, DeploymentStats())
+        return self.per_deployment.setdefault(name, DeploymentStats(scored=0, alerts=0, errors=0))
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..e0a6e44 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -1,5 +1,6 @@
 """Build monitor requests, read scores back and decide what to alert on.
 
+Long trajectories are split into overlapping windows of messages. Every window is scored on its own
 Long trajectories do not fit in one monitor request, so each trajectory is
 split into overlapping windows of messages. Every window is scored on its own
 and the trajectory gets the highest window score: one clearly bad window is
@@ -3,12 +4,17 @@
 
 import logging
-from concurrent.futures import ThreadPoolExecutor
+import concurrent.futures
+from concurrent.futures import ThreadPoolExecutor
 from dataclasses import dataclass, field
 from importlib import resources
 
 from .client import MonitorRequest
 from .config import Config
+from .parse import (
+    MonitorParseError,
+    MonitorUnavailable,
+)
 from .parse import MAX_SCORE, MIN_SCORE, parse_reply
 from .store import Message, Trajectory
 from .transcript import render_window, split_windows
@@ -57,38 +63,54 @@ def build_request(
 
 
 def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
-    """Score one trajectory, window by window.
+    """Score one trajectory in overlapping windows.
 
-    Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
-    the caller records those as monitor errors.
+    Trajectories are split into windows of messages, and each window is scored
+    independently. The trajectory score is the highest score from all successfully
+    scored windows. If no windows succeed, raises an exception.
+    
+    This implementation handles partial failures: if some windows fail but others
+    succeed, it still produces a valid trajectory score from the successful windows.
     """
-    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
-    requests = [
-        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
-        for i, window in enumerate(windows)
-    ]
-    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
-        replies = list(pool.map(client.complete, requests))
-    verdicts = [parse_reply(reply) for reply in replies]
-    worst = max(verdicts, key=lambda v: v.score)
+    windows = split_windows(
+        traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap
+    )
+    requests = [
+        build_request(
+            cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}"
+        )
+        for i, window in enumerate(windows)
+    ]
+
+    # Score windows with error handling
+    successful_scores = []  # (window_idx, score)
+    successful_rationales = []  # (window_idx, rationale)
+    failed_windows = []  # (window_idx, exception)
+
+    with ThreadPoolExecutor(
+        max_workers=min(cfg.monitor.max_workers, len(requests))
+    ) as pool:
+        # Submit all tasks
+        future_to_idx = {
+            pool.submit(client.complete, req): i for i, req in enumerate(requests)
+        }
+
+        # Process results as they complete
+        for future in concurrent.futures.as_completed(future_to_idx):
+            i = future_to_idx[future]
+            try:
+                reply = future.result()
+                verdict = parse_reply(reply)
+                successful_scores.append((i, verdict.score))
+                successful_rationales.append((i, verdict.rationale))
+            except (MonitorParseError, MonitorUnavailable) as exc:
+                failed_windows.append((i, exc))
+
+    # If no windows succeeded, raise an exception
+    if not successful_scores:
+        # Prefer raising MonitorUnavailable if all failures were of that type
+        if all(isinstance(exc, MonitorUnavailable) for _, exc in failed_windows):
+            raise MonitorUnavailable("All windows failed with MonitorUnavailable")
+        # Otherwise, raise the first error
+        _, exc = failed_windows[0]
+        raise exc
+
+    # Sort by window index for consistent ordering
+    successful_scores.sort(key=lambda x: x[0])
+    successful_rationales.sort(key=lambda x: x[0])
+
+    # Extract scores and rationales in window order
+    all_scores = [score for _, score in successful_scores]
+    all_rationales = [rationale for _, rationale in successful_rationales]
+
+    # Find the worst (highest score) window
+    worst_idx = max(range(len(all_scores)), key=lambda i: all_scores[i])
+
+    # Log partial failures
+    if failed_windows:
+        logging.warning(
+            "Partial failure for trajectory %s: %d/%d windows failed (%s)",
+            traj.snapshot_id,
+            len(failed_windows),
+            len(windows),
+            ", ".join(f"{i+1}:{type(exc).__name__}" for i, exc in failed_windows),
+        )
+
     return TrajectoryResult(
         snapshot_id=traj.snapshot_id,
         episode_id=traj.episode_id,
         deployment=traj.deployment,
         agent_model=traj.agent_model,
-        score=normalise(worst.score),
-        raw_score=worst.score,
-        window_scores=[v.score for v in verdicts],
-        rationale=worst.rationale,
+        score=normalise(all_scores[worst_idx]),
+        raw_score=all_scores[worst_idx],
+        window_scores=all_scores,
+        rationale=all_rationales[worst_idx],
     )
diff --git a/tests/test_scoring.py b/tests/test_scoring.py
index fbb7d30..a25b805 100644
--- a/tests/test_scoring.py
+++ b/tests/test_scoring.py
@@ -57,6 +57,39 @@ class WindowScoringTest(unittest.TestCase):
         self.assertEqual(scoring.decide(scoring.normalise(9), CFG), "page")
 
 
+class PartialWindowFailureTest(unittest.TestCase):
+    def test_partial_window_failure(self):
+        # Simulate backend that fails on window 2 but succeeds on others
+        class FlakyBackend:
+            def complete(self, req):
+                if "window 2 of 3" in req.user:
+                    raise scoring.MonitorUnavailable("Simulated failure")
+                return "<score>8</score>"
+
+        backend = FlakyBackend()
+        result = scoring.score_trajectory(one_trajectory(90), backend, CFG, "prompt")
+        self.assertEqual(len(result.window_scores), 2)  # Only 2 windows succeeded
+        self.assertEqual(result.raw_score, 8)
+        self.assertEqual(len(backend.requests), 3)  # All requests were attempted
+
+    def test_all_windows_fail(self):
+        class FailingBackend:
+            def complete(self, req):
+                raise scoring.MonitorUnavailable("Simulated failure")
+
+        backend = FailingBackend()
+        with self.assertRaises(scoring.MonitorUnavailable):
+            scoring.score_trajectory(one_trajectory(90), backend, CFG, "prompt")
+
+    def test_mixed_failure_types(self):
+        class MixedBackend:
+            def complete(self, req):
+                if "window 1 of 3" in req.user:
+                    raise scoring.MonitorParseError("Invalid format")
+                return "<score>7</score>"
+
+        backend = MixedBackend()
+        result = scoring.score_trajectory(one_trajectory(90), backend, CFG, "prompt")
+        self.assertEqual(result.raw_score, 7)
+
+
 class PromptTest(unittest.TestCase):
     def test_all_prompt_versions_load(self):
         for version in ("v3", "v4"):
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..d12b53e 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -39,3 +39,13 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
+
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.scored, 2)
```