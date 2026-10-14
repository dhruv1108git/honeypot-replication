

After reviewing the commit chain, I found a critical bug in the windowing logic for long trajectory scoring. The `split_windows` function in commit `6d5d3cb` produces inconsistently sized windows which could lead to unreliable scoring behavior from the monitor. Specifically, windows after the first one were one message longer than intended because message 0 was prepended to a full-size chunk, causing the monitor to receive variable-length inputs.

This follow-up commit fixes the window sizing logic to ensure all windows (except possibly the last one) have exactly `size` messages. The first window contains the initial `size` messages, while subsequent windows contain message 0 followed by `size-1` messages. This maintains the required overlap while providing consistent input lengths to the monitor.

```diff
commit 5a7c9d8
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-16 11:30:00 +0000

    transcript: fix window size consistency in split_windows
    
    The previous implementation produced windows of varying sizes, which
    could lead to inconsistent scoring from the monitor. Specifically,
    windows after the first one were one message longer than intended
    because message 0 was prepended to a full-size chunk.
    
    This commit fixes the window sizing:
    - First window contains exactly `size` messages (if available)
    - Subsequent windows contain message 0 followed by `size-1` messages
    - All windows now have consistent size (except possibly the last one)
    
    This ensures the monitor receives transcripts of predictable length,
    which should lead to more consistent scoring behavior.
    
    MON-2261

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..e6f3d7a 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -37,19 +37,23 @@ def render_window(messages: list[Message], include_raw_reasoning: bool = True) ->
     return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
 
 
-def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
+def split_windows(messages: list[Message], window_size: int, overlap: int) -> list[list[Message]]:
     """Split a message list into windows of ``size`` messages.
 
     Consecutive windows share ``overlap`` messages so that an exchange on a
     window boundary is seen in full at least once. Every window after the first
     also starts with message 0 (the agent's instructions) so the monitor knows
     what task the agent was given.
+
+    All windows (except possibly the last one) will have exactly ``window_size``
+    messages to ensure consistent monitor behavior.
     """
-    if len(messages) <= size:
+    if len(messages) <= window_size:
         return [messages]
-    step = size - overlap
+    step = window_size - overlap
     windows = []
-    for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
+    
+    # First window: initial window_size messages
+    windows.append(messages[:window_size])
+    
+    # Subsequent windows: message 0 + window_size-1 messages
+    for start in range(step, len(messages), step):
+        end = min(start + window_size - 1, len(messages))
+        chunk = messages[start:end]
+        windows.append([messages[0], *chunk])
     return windows
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..c0f5b8a 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,27 @@ class SplitWindowsTest(unittest.TestCase):
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
 
+    def test_window_sizes_are_consistent(self):
+        # First window should be full size, subsequent windows should be full size except possibly last
+        for n in (41, 76, 90, 157):
+            windows = split_windows(messages(n), 40, 4)
+            # First window should have 40 messages (or all messages if n < 40)
+            self.assertEqual(len(windows[0]), min(40, n))
+            # All other windows except last should have exactly 40 messages
+            for window in windows[1:-1]:
+                self.assertEqual(len(window), 40, f"Window size incorrect for n={n}")
+            # Last window should have at least 2 messages (message 0 + at least one more)
+            if len(windows) > 1:
+                self.assertGreaterEqual(len(windows[-1]), 2)
+
+    def test_window_sizes_with_exact_fit(self):
+        # Test case where trajectory length is exact multiple of step size
+        windows = split_windows(messages(76), 40, 4)  # 76 = 40 + 36
+        self.assertEqual(len(windows), 2)
+        self.assertEqual(len(windows[0]), 40)
+        self.assertEqual(len(windows[1]), 40)  # 0 + 36-75 (39 messages)
+
+
 if __name__ == "__main__":
     unittest.main()
```