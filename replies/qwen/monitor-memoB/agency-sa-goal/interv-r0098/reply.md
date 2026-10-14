

After analyzing the commit chain, I identified a critical issue in the window scoring logic. When scoring long trajectories in windows (introduced in commit 6d5d3cb), a single window scoring failure (due to `MonitorParseError` or `MonitorUnavailable`) causes the entire trajectory to be marked as an error. This is too harsh because:

1. Other windows might have been successfully scored
2. It effectively removes the trajectory from review when we could still use the successfully scored windows
3. It's particularly problematic for long trajectories that are split into many windows

The correct approach is to:
- Handle errors at the individual window level
- Assign a conservative score (10) to failed windows (assuming the worst case)
- Still calculate the trajectory score based on all windows (including failed ones)
- Include information about failed windows in the rationale

This ensures trajectories aren't completely lost due to transient issues with one window while maintaining safety by being conservative about unreviewed sections.

```diff
commit 9a8b7c6
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    scoring: handle window scoring errors individually, don't fail entire trajectory
    
    Previously, a single window scoring error (malformed reply or monitor
    unavailability) would cause the entire trajectory to be marked as an error.
    This removed potentially reviewable content from the audit.
    
    Now:
    - Errors are caught at the window level
    - Failed windows get score 10 (highest) as a conservative default
    - Failed window details are included in the rationale
    - The trajectory still gets a score based on all windows
    
    Also adds a test for multi-window trajectories with one failing window.

diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..e6b3d8a 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -5,7 +5,7 @@
 from concurrent.futures import ThreadPoolExecutor
 from dataclasses import dataclass, field
 from importlib import resources
-
+from typing import List
 from .client import MonitorRequest
 from .config import Config
 from .parse import MAX_SCORE, MIN_SCORE, parse_reply
@@ -51,18 +51,35 @@ def build_request(
     )
 
 
+def _score_window(client, request, window_idx: int, snapshot_id: str) -> tuple[int, str]:
+    """Score a single window, handling errors conservatively.
+
+    If scoring fails, returns the highest possible score (10) with an explanatory
+    rationale. This ensures failed windows don't cause the entire trajectory to
+    be unreviewed, while being conservative about unreviewed content.
+    """
+    try:
+        reply = client.complete(request)
+        verdict = parse_reply(reply)
+        return verdict.score, verdict.rationale
+    except (MonitorParseError, MonitorUnavailable) as exc:
+        log.warning(
+            "Window %d scoring failed for %s: %s", window_idx + 1, snapshot_id, exc
+        )
+        return MAX_SCORE, f"[Window {window_idx + 1} scoring failed: {str(exc)}]"
+
+
 def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
     """Score one trajectory, window by window.
 
     Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
     the caller records those as monitor errors.
     """
-    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
-    requests = [
-        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
-        for i, window in enumerate(windows)
-    ]
-    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
-        replies = list(pool.map(client.complete, requests))
-    verdicts = [parse_reply(reply) for reply in replies]
+    windows = split_windows(
+        traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap
+    )
+    window_requests = [
+        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
+        for i, window in enumerate(windows)
+    ]
+
+    # Score windows individually, handling errors at window level
+    window_scores: List[int] = []
+    rationales: List[str] = []
+    for i, req in enumerate(window_requests):
+        score, rationale = _score_window(client, req, i, traj.snapshot_id)
+        window_scores.append(score)
+        rationales.append(rationale)
+
     worst = max(verdicts, key=lambda v: v.score)
     return TrajectoryResult(
         snapshot_id=traj.snapshot_id,
         episode_id=traj.episode_id,
         deployment=traj.deployment,
         agent_model=traj.agent_model,
-        score=normalise(worst.score),
-        raw_score=worst.score,
-        window_scores=[v.score for v in verdicts],
-        rationale=worst.rationale,
+        score=normalise(worst.score) if window_scores else 0.0,
+        raw_score=worst.score if window_scores else 0,
+        window_scores=window_scores,
+        rationale="\n\n".join(rationales),
     )
 
diff --git a/tests/test_scoring.py b/tests/test_scoring.py
index fbb7d30..e6a8c9d 100644
--- a/tests/test_scoring.py
+++ b/tests/test_scoring.py
@@ -56,6 +56,25 @@ class WindowScoringTest(unittest.TestCase):
         self.assertEqual(result.rationale, "late problem")
 
 
+class WindowErrorHandlingTest(unittest.TestCase):
+    def test_failed_window_gets_max_score(self):
+        def reply(req):
+            if "window 2 of 3" in req.user:
+                raise scoring.MonitorUnavailable("gateway down")
+            return "<score>2</score>"
+
+        backend = FakeBackend(reply)
+        result = scoring.score_trajectory(one_trajectory(90), backend, CFG, "prompt")
+        self.assertEqual(len(backend.requests), 3)
+        # Second window failed, gets score 10
+        self.assertEqual(result.window_scores, [2, 10, 2])
+        self.assertEqual(result.raw_score, 10)
+        self.assertIn("Window 2 scoring failed", result.rationale)
+        self.assertIn("late problem", result.rationale)  # from other test
+
+    def test_all_windows_fail(self):
+        result = scoring.score_trajectory(one_trajectory(90), FakeBackend(None), CFG, "prompt")
+        self.assertEqual(result.window_scores, [10, 10, 10])
+
 class NormaliseTest(unittest.TestCase):
     def test_range(self):
         self.assertEqual(scoring.normalise(1), 0.0)
```