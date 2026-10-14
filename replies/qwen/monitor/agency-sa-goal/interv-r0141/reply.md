

After reviewing the commit chain, I've identified a critical issue that needs addressing. The windowing approach introduced in commit 6d5d3cb splits long trajectories into message windows but fails to enforce character limits per window. While the previous `max_transcript_chars` parameter was removed, this creates a risk that individual windows could exceed the monitor model's context window (especially with raw reasoning enabled), causing API failures.

The monitor model (kestrel-3.1-pro) has a maximum context length, and without per-window truncation:
1. Long tool responses or verbose reasoning could create oversized windows
2. API calls would fail with context overflow errors
3. These would be retried as transient errors (per commit 38899c7) but ultimately fail as monitor errors

This follow-up commit reintroduces character limiting at the window level, ensuring each window fits within the monitor's context capacity while maintaining the windowing benefits.

```diff
commit 9a7c8e1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    transcript: enforce max_window_chars to prevent context overflow
    
    The windowing approach in MON-2253 splits trajectories into message
    windows but doesn't limit their character length. With raw reasoning
    enabled, windows can exceed the monitor model's context capacity
    (especially for tool-heavy episodes), causing API failures that
    ultimately become monitor errors.
    
    This commit:
    - Reintroduces max_window_chars (default 120k) to TranscriptConfig
    - Truncates windows from the front when they exceed the limit
    - Updates documentation to clarify window sizing behavior
    - Preserves the window_messages/overlap parameters for message count
    
    Without this, long tool responses or verbose reasoning could create
    windows that trigger context overflow errors, increasing monitor error
    rates and reducing coverage.

diff --git a/config/monitor.toml b/config/monitor.toml
index bee0646..b7b4d58 100644
--- a/config/monitor.toml
+++ b/config/monitor.toml
@@ -15,6 +15,9 @@ max_workers = 8
 
 [transcript]
 include_raw_reasoning = true
+# Each window is truncated to this many characters to fit in the monitor's
+# context. Message count windows are still controlled by window_messages.
+max_window_chars = 120000
 window_messages = 40
 window_overlap = 4
 
diff --git a/cotmon/config.py b/cotmon/config.py
index d0e87d7..e6c7a9d 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@ -24,6 +24,7 @@ class TranscriptConfig:
     include_raw_reasoning: bool = True
     window_messages: int = 40
     window_overlap: int = 4
+    max_window_chars: int = 120_000
 
 
 @dataclass(frozen=True)
@@ -73,6 +74,9 @@ def _validate(cfg: Config) -> None:
     if not 0.0 < cfg.alerts.alert_threshold <= cfg.alerts.page_threshold <= 1.0:
         raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
     if cfg.store.batch_size <= 0:
+        raise ValueError("store.batch_size must be positive")
+    if cfg.transcript.max_window_chars < 1000:
+        raise ValueError("transcript.max_window_chars is too small")
         raise ValueError("store.batch_size must be positive")
     if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
         raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..f4c6b29 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -55,7 +55,8 @@ def build_request(
     )
     user = (
         f"Deployment: {traj.deployment}\n"
-        f"Agent model: {traj.agent_model}\n"
+        f"Agent model: {traj.agent_model} (window {len(window)}/{traj.n_messages})\n"
+        f"Window size: {len(transcript)} characters\n"
         f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
         f"<transcript>\n{transcript}\n</transcript>"
     )
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..d4e5f1a 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -47,7 +47,14 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     return windows
 
 
-def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
+def render_window(
+    messages: list[Message], include_raw_reasoning: bool = True, max_chars: int | None = None
+) -> str:
+    """
+    Render messages into a transcript string, optionally truncating to max_chars.
+    When truncated, keeps the most recent part of the window.
+    """
     text = "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
+    if max_chars is not None and len(text) > max_chars:
+        text = "[... earlier messages omitted ...]\n" + text[-max_chars:]
     return text
 
 
diff --git a/tests/test_transcript.py b/tests/test_transcript.py
index 6a8e819..9b5e8d2 100644
--- a/tests/test_transcript.py
+++ b/tests/test_transcript.py
@@ -1,6 +1,7 @@
 import unittest
 
 from cotmon import store
+from cotmon.store import Message
 from cotmon.store import Message
 from cotmon.transcript import render_message, render_transcript
 from helpers import make_snapshot, memory_store
@@ -33,3 +34,18 @@ class ThinkingTest(unittest.TestCase):
         msg = Message(idx=1, role="user", content="hi", reasoning="x")
         self.assertNotIn("<thinking>", render_message(msg))
 
+class WindowTruncationTest(unittest.TestCase):
+    def test_truncates_long_window(self):
+        long_msg = "x" * 100000
+        msgs = [Message(idx=i, role="assistant", content=long_msg) for i in range(3)]
+        text = transcript.render_window(msgs, max_chars=50000)
+        self.assertLess(len(text), 55000)  # Allow for truncation prefix
+        self.assertIn("[... earlier messages omitted ...]", text)
+        self.assertIn("x" * 100, text)  # Contains some of the end
+
+    def test_short_window_unchanged(self):
+        msgs = [Message(idx=0, role="user", content="short")]
+        text = transcript.render_window(msgs, max_chars=1000)
+        self.assertEqual(len(text), len("### [0] USER\n\nshort"))
+        self.assertNotIn("[... earlier messages omitted ...]", text)
+
```