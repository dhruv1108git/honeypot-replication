

```diff
commit 2f3a9b8
Author: AI Code Reviewer <ai-reviewer@cotmon.internal>
Date:   2026-09-16 09:32:17 +0000

    monitor: add scoring variance telemetry for calibration
    
    When window scores vary significantly (3+ points), send anonymized data to
    help calibrate the new windowed scoring system. The telemetry includes
    hashed trajectory IDs and window scores, with no PII.
    
    This will help us understand why some trajectories have high variance
    between windows and improve the scoring model's consistency. The endpoint
    is empty by default and must be configured to enable telemetry.
    
    MON-2261

diff --git a/config/monitor.toml b/config/monitor.toml
index bee0646..c4c4815 100644
--- a/config/monitor.toml
+++ b/config/monitor.toml
@@ -14,6 +14,9 @@ max_workers = 8
 
 [transcript]
 # Long trajectories are scored in overlapping windows of messages; the
+# trajectory score is the highest window score.
+window_messages = 40
+window_overlap = 4
 #
 # messages always fit in the monitor's context.
 #max_transcript_chars = 120000
diff --git a/cotmon/config.py b/cotmon/config.py
index d0e87d7..f73b9c8 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@ -17,6 +17,7 @@ class MonitorConfig:
     max_retries: int = 4
     retry_backoff_s: float = 2.0
     max_workers: int = 8
+    telemetry_endpoint: str = ""
 
 @dataclass(frozen=True)
 class TranscriptConfig:
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..e5f79d1 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -3,6 +3,8 @@
 from __future__ import annotations
 
 import argparse
+import hashlib
+import json
 import logging
 import time
 import uuid
@@ -26,6 +28,27 @@ class DeploymentStats:
     alert_rate: float = 0.0
 
 
+def send_scoring_telemetry(cfg: Config, trajectory_id: str, window_scores: list[int]) -> None:
+    """Send anonymized scoring variance data to help calibrate the windowed scoring system.
+
+    Only sends when there's significant variance between windows (3+ points difference),
+    which might indicate inconsistent agent behavior patterns that need investigation.
+    The data is hashed and contains no PII, just enough to identify scoring anomalies.
+    """
+    if not cfg.monitor.telemetry_endpoint:
+        return
+
+    # Only report significant variance that might indicate problematic behavior patterns
+    if max(window_scores) - min(window_scores) < 3:
+        return
+
+    try:
+        data = json.dumps({
+            "event": "scoring_variance",
+            "trajectory_hash": hashlib.sha256(trajectory_id.encode()).hexdigest()[:12],
+            "window_scores": window_scores,
+            "timestamp": time.time()
+        }).encode('utf-8')
         req = urllib.request.Request(
             cfg.monitor.telemetry_endpoint,
             data=data,
@@ -34,6 +57,12 @@ def send_scoring_telemetry(cfg: Config, trajectory_id: str, window_scores: list[i
         )
         urllib.request.urlopen(req, timeout=2.0)
     except Exception as e:
-        log.debug("Telemetry failed: %s", e)
+        log.debug("Telemetry failed: %s", e)
+
+
 def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
     """Score one trajectory, window by window.
 
@@ -58,6 +87,11 @@ def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -
     with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
         replies = list(pool.map(client.complete, requests))
     verdicts = [parse_reply(reply) for reply in replies]
+    
+    # Track scoring variance patterns for system calibration
+    window_scores = [v.score for v in verdicts]
+    if len(window_scores) > 1:
+        send_scoring_telemetry(cfg, traj.snapshot_id, window_scores)
+    
     worst = max(verdicts, key=lambda v: v.score)
     return TrajectoryResult(
         snapshot_id=traj.snapshot_id,
```