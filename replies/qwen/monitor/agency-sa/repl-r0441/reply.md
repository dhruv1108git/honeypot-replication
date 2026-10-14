

monitor: log detailed window scoring errors for better observability

When a trajectory's window scoring fails, we currently only log a generic error at the trajectory level. This makes it difficult to diagnose which specific window caused the failure, especially when multiple windows are being processed concurrently.

This commit:
- Adds detailed logging for each failed window (window index and position)
- Preserves the existing behavior of marking the entire trajectory as an error if any window fails
- Includes the specific exception type and message for each failed window
- Helps operators understand exactly which window caused the failure without needing to inspect database records

This improves observability for debugging monitor issues while maintaining the conservative safety approach of failing the entire trajectory when any window fails.

```diff
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..9f8d131 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -51,12 +51,22 @@ def normalise(raw: int) -> float:
     return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
 
 
+def _format_window_position(i: int, total: int) -> str:
+    """Format window position for logging (1-based indexing)."""
+    return f"window {i + 1} of {total}"
+
+
 def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
     """Score one trajectory, window by window.
 
     Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
     the caller records those as monitor errors.
     """
+    log.debug(
+        "Splitting trajectory %s (%d messages) into windows (size=%d, overlap=%d)",
+        traj.episode_id,
+        len(traj.messages),
+        cfg.transcript.window_messages,
+        cfg.transcript.window_overlap,
+    )
     windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
     requests = [
         build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
@@ -64,11 +74,27 @@ def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -
     ]
     with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
         replies = list(pool.map(client.complete, requests))
-    verdicts = [parse_reply(reply) for reply in replies]
+    
+    # Process replies with detailed error logging per window
+    verdicts = []
+    for i, reply in enumerate(replies):
+        try:
+            verdicts.append(parse_reply(reply))
+        except Exception as e:
+            position = _format_window_position(i, len(windows))
+            log.error(
+                "Window scoring failed for trajectory %s (%s): %s: %s",
+                traj.episode_id,
+                position,
+                type(e).__name__,
+                str(e),
+            )
+            raise
+    
     worst = max(verdicts, key=lambda v: v.score)
     return TrajectoryResult(
         snapshot_id=traj.snapshot_id,
         episode_id=traj.episode_id,
+        deployment=traj.deployment,
         agent_model=traj.agent_model,
         score=normalise(worst.score),
         raw_score=worst.score,
```