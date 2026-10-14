

# scoring: be resilient to individual window failures

Currently, if any window fails to score (e.g., due to a transient gateway error), the entire trajectory is marked as failed. This is too strict - if some windows succeed, we should use the highest score from the successful windows.

This change makes the window scoring more resilient:
- If some windows fail but others succeed, return the highest score from successful windows
- Add a warning to the rationale about failed windows
- Only fail the whole trajectory if all windows fail
- Properly track which specific windows succeeded/failed

This improves reliability during transient gateway issues and reduces false positives in monitor error reporting.

```diff
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..196111b 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -1,13 +1,15 @@
 """Build monitor requests, read scores back and decide what to alert on.
 
 Long trajectories do not fit in one monitor request, so each trajectory is
-split into overlapping windows of messages. Every window is scored on its own
-and the trajectory gets the highest window score: one clearly bad window is
-enough to alert.
+split into overlapping windows of messages. Every window is scored on its own.
+If some windows fail but others succeed, the trajectory gets the highest score
+from the successful windows. Only fails the whole trajectory if all windows fail.
 """
 
 from __future__ import annotations
 
 import logging
+import concurrent.futures
 from concurrent.futures import ThreadPoolExecutor
 from dataclasses import dataclass, field
 from importlib import resources
@@ -55,41 +57,55 @@ def build_request(
     )
 
 
+def normalise(raw: int) -> float:
+    """Map a monitor score from the 1-10 scale onto [0, 1]."""
+    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
+
+
 def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
     """Score one trajectory, window by window.
 
-    Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
-    the caller records those as monitor errors.
+    If some windows fail but others succeed, returns the highest score from
+    the successful windows. Only fails the whole trajectory if all windows fail.
+    Failed windows are noted in the rationale and recorded in window_scores as -1.
     """
     windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
     requests = [
         build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
         for i, window in enumerate(windows)
     ]
-    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
-        replies = list(pool.map(client.complete, requests))
-    verdicts = [parse_reply(reply) for reply in replies]
-    worst = max(verdicts, key=lambda v: v.score)
-    return TrajectoryResult(
-        snapshot_id=traj.snapshot_id,
-        episode_id=traj.episode_id,
-        deployment=traj.deployment,
-        agent_model=traj.agent_model,
-        score=normalise(worst.score),
-        raw_score=worst.score,
-        window_scores=[v.score for v in verdicts],
-        rationale=worst.rationale,
-    )
+
+    # Initialize results with placeholders
+    window_scores = [-1] * len(windows)  # -1 indicates failed window
+    successful_verdicts = []  # (index, verdict)
+    errors = []
+
+    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
+        # Submit all requests
+        future_to_idx = {pool.submit(client.complete, req): i for i, req in enumerate(requests)}
+
+        # Process completed futures
+        for future in concurrent.futures.as_completed(future_to_idx):
+            idx = future_to_idx[future]
+            try:
+                reply = future.result()
+                verdict = parse_reply(reply)
+                window_scores[idx] = verdict.score
+                successful_verdicts.append((idx, verdict))
+            except (MonitorParseError, MonitorUnavailable) as exc:
+                errors.append((idx, exc))
+
+    # If we have successful windows, return the highest score
+    if successful_verdicts:
+        worst_idx, worst_verdict = max(successful_verdicts, key=lambda x: x[1].score)
+
+        # Create a rationale that mentions failed windows
+        if errors:
+            failed_windows = ", ".join(str(idx + 1) for idx, _ in errors)
+            rationale = f"WARNING: {len(errors)}/{len(windows)} windows failed to score (windows {failed_windows}).\n\n{worst_verdict.rationale}"
+        else:
+            rationale = worst_verdict.rationale
+
+        return TrajectoryResult(
+            snapshot_id=traj.snapshot_id,
+            episode_id=traj.episode_id,
+            deployment=traj.deployment,
+            agent_model=traj.agent_model,
+            score=normalise(worst_verdict.score),
+            raw_score=worst_verdict.score,
+            window_scores=window_scores,
+            rationale=rationale,
+        )
+
+    # All windows failed - raise the first error
+    _, first_error = errors[0]
+    raise first_error
```