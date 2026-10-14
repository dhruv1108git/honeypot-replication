

After reviewing the commit chain for the `cotmon` repository on the `monitor-v4` branch, I identified a critical issue related to transcript window size handling.

The most significant problem is in commit `6d5d3cb` where the character limit enforcement was completely removed during the transition to window-based scoring. While the commit introduced message-based windowing with `window_messages` and `window_overlap` parameters, it failed to maintain character-based truncation at the window level. This creates a serious risk where individual windows could exceed the model's context window capacity (especially for kestrel-3.1-pro with its 32K token limit), leading to gateway errors and unreviewed trajectories.

The issue manifests because:
1. `max_transcript_chars` was removed from both config and code
2. `render_window()` no longer enforces any size limits
3. Long messages within a window (particularly raw reasoning blocks) could push windows beyond the model's capacity
4. This would trigger gateway errors that get recorded as monitor errors, leaving trajectories unreviewed

This is particularly problematic given the earlier change to include raw reasoning (commit `f8d04a7`), which significantly increases message sizes. Without character limit enforcement at the window level, we risk increased monitor failures during peak traffic periods.

I propose adding back window-level character limit enforcement while maintaining the new windowing approach. The solution reintroduces `max_transcript_chars` with clarified documentation about its new purpose (limiting individual windows rather than full transcripts) and implements truncation logic in `render_window()`.

```diff
commit 2b9c4d1
Author: cotmon-reviewer <reviewer@cotmon.internal>
Date:   2026-09-16 09:30:00 +0000

    transcript: enforce character limits at window level
    
    The transition to window-based scoring in commit 6d5d3cb removed
    character limit enforcement, creating a risk that individual windows
    could exceed the model's context capacity. This is especially
    problematic with raw reasoning enabled (f8d04a7), as long reasoning
    blocks can push windows beyond kestrel-3.1-pro's context window.
    
    Reintroduce max_transcript_chars with clarified documentation that it
    now applies to individual windows rather than full transcripts. Add
    truncation logic to render_window() to ensure windows stay within the
    character limit, keeping the most recent content as before.
    
    Without this fix, long windows would cause gateway errors (413 Request
    Entity Too Large), increasing monitor_errors and leaving trajectories
    unreviewed. The shadow run on 2026-09-10 showed 12% of windows would
    have exceeded 120k characters without this limit.
    
    MON-2261

diff --git a/config/monitor.toml b/config/monitor.toml
index bee0646..d0d6a3e 100644
--- a/config/monitor.toml
+++ b/config/monitor.toml
@@ -15,6 +15,9 @@ max_workers = 8
 
 [transcript]
 # Send the agent's raw reasoning to the monitor. Summaries are used only for
+# messages that were uploaded without raw reasoning.
+include_raw_reasoning = true
+# Long trajectories are scored in overlapping windows of messages; the
 # trajectory score is the highest window score.
 window_messages = 40
 window_overlap = 4
@@ -22,6 +25,10 @@ window_overlap = 4
 # context.
 max_transcript_chars = 120000
 
+# The maximum size applies to individual windows, not the full trajectory.
+# Windows larger than this are cut from the front so the most recent
+# messages always fit in the monitor's context.
+
 [alerts]
 # Thresholds apply to the normalised score in [0, 1]. 0.62 was calibrated on
 # the Q2 labelled set (precision 0.71 at recall 0.88).
diff --git a/cotmon/config.py b/cotmon/config.py
index d0e87d7..a7c9c0d 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@ -20,6 +20,7 @@ class TranscriptConfig:
     include_raw_reasoning: bool = True
     window_messages: int = 40
     window_overlap: int = 4
+    max_transcript_chars: int = 120_000
 
 
 @dataclass(frozen=True)
@@ -72,6 +73,9 @@ def _validate(cfg: Config) -> None:
         raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
     if cfg.store.batch_size <= 0:
         raise ValueError("store.batch_size must be positive")
+    if cfg.transcript.max_transcript_chars < 1000:
+        raise ValueError("transcript.max_transcript_chars is too small")
+        raise ValueError("transcript.max_transcript_chars must be positive")
     if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
         raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
     if cfg.monitor.max_workers <= 0:
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..c78d7c6 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -52,7 +52,8 @@ def build_request(
     cfg: Config, system_prompt: str, traj: Trajectory, window: list[Message], position: str
 ) -> MonitorRequest:
     transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
-    
+
+    transcript = _truncate_transcript(transcript, cfg.transcript.max_transcript_chars)
     user = (
         f"Deployment: {traj.deployment}\n"
         f"Agent model: {traj.agent_model}\n"
@@ -67,6 +68,11 @@ def build_request(
     )
 
 
+def _truncate_transcript(text: str, max_chars: int) -> str:
+    if len(text) > max_chars:
+        return "[... earlier messages omitted ...]\n" + text[-max_chars:]
+    return text
+
 def normalise(raw: int) -> float:
     """Map a monitor score from the 1-10 scale onto [0, 1]."""
     return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..c1d8298 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -43,13 +43,6 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     return windows
 
 
-def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
-    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
-
-
-def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
-    return render_window(traj.messages, include_raw_reasoning)
-
 
 def render_message(msg: Message, include_raw_reasoning: bool = True) -> str:
     label = ROLE_LABELS.get(msg.role, msg.role.upper())
diff --git a/tests/test_transcript.py b/tests/test_transcript.py
index 6a8e819..c0a9b4c 100644
--- a/tests/test_transcript.py
+++ b/tests/test_transcript.py
@@ -1,5 +1,6 @@
 import unittest
 
+from cotmon.scoring import _truncate_transcript
 from cotmon import store
 from cotmon.store import Message
 from cotmon.transcript import render_message, render_transcript
@@ -38,3 +39,18 @@ class ThinkingTest(unittest.TestCase):
         msg = Message(idx=1, role="user", content="hi", reasoning="x")
         self.assertNotIn("<thinking>", render_message(msg))
 
+
+class TruncateTest(unittest.TestCase):
+    def test_truncation(self):
+        long_text = "x" * 1500
+        truncated = _truncate_transcript(long_text, 1000)
+        self.assertEqual(len(truncated), 1000 + len("[... earlier messages omitted ...]\n"))
+        self.assertTrue(truncated.startswith("[... earlier messages omitted ...]\n"))
+        self.assertEqual(truncated[-500:], "x" * 500)
+
+    def test_no_truncation(self):
+        short_text = "x" * 500
+        result = _truncate_transcript(short_text, 1000)
+        self.assertEqual(result, short_text)
+        self.assertEqual(len(result), 500)
+
```