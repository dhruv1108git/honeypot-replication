

# Review Summary

After reviewing the commit chain, I identified a critical bug in the trajectory windowing logic. The `split_windows` function creates inconsistent window sizes - subsequent windows are 1 message larger than the first window due to adding the instructions message without adjusting the chunk size. This can cause token limit issues with the monitor model.

## Critical Bug Details

In `cotmon/transcript.py`:
```python
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

When processing subsequent windows, this adds the instructions message (message 0) to the chunk without reducing the chunk size, resulting in windows that are `window_messages + 1` messages long instead of the configured `window_messages`. For example, with the default config (40 messages per window), the first window has 40 messages while subsequent windows have 41.

This inconsistency can:
1. Cause token limit errors with the monitor model
2. Create unpredictable behavior in scoring
3. Skew evaluation metrics between windows

## Follow-up Commit

The fix ensures all windows (except possibly the last) have exactly the configured size by reserving one slot for the instructions message in subsequent windows. I've also added tests to verify window sizes.

```diff
commit 0f4a7d1
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-16 12:35:22 +0000

    fix: ensure consistent window sizes in trajectory splitting
    
    The windowing logic was creating inconsistent window sizes: subsequent
    windows were 1 message larger than the first window because the
    instructions message (message 0) was added without adjusting the chunk
    size. This could cause token limit issues with the monitor model.
    
    Now all windows (except possibly the last) have exactly the configured
    size. For subsequent windows, we reserve one slot for the instructions
    message, so we take (window_messages - 1) messages from the trajectory.
    
    Added tests to verify window sizes and overlap behavior.

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..d06d0b1 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -38,18 +38,25 @@ def render_window(messages: list[Message], include_raw_reasoning: bool = True) ->
     return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
 
 
-def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
+def split_windows(messages: list[Message], window_size: int, overlap: int) -> list[list[Message]]:
     """Split a message list into windows of ``size`` messages.
 
     Consecutive windows share ``overlap`` messages so that an exchange on a
     window boundary is seen in full at least once. Every window after the first
     also starts with message 0 (the agent's instructions) so the monitor knows
     what task the agent was given.
     """
-    if len(messages) <= size:
+    if len(messages) <= window_size:
         return [messages]
-    step = size - overlap
+
+    # For subsequent windows, reserve one slot for the instructions message
+    adjusted_size = window_size - 1
+    step = adjusted_size - overlap
     windows = []
-    for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
+    
+    # First window: take full window_size messages
+    windows.append(messages[:window_size])
+    
+    # Subsequent windows
+    for start in range(step, len(messages) - overlap, step):
+        chunk = messages[start : start + adjusted_size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
 
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..6b9c71e 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -23,6 +23,25 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_all_windows_except_last_have_configured_size(self):
+        # Test with trajectory longer than window size
+        windows = split_windows(messages(90), 40, 4)
+        self.assertEqual(len(windows[0]), 40)  # First window
+        self.assertEqual(len(windows[1]), 40)  # Second window
+        self.assertEqual(len(windows[2]), 21)  # Last window (shorter)
+
+        # Test with trajectory exactly window size + 1
+        windows = split_windows(messages(41), 40, 4)
+        self.assertEqual(len(windows[0]), 40)
+        self.assertEqual(len(windows[1]), 2)   # [0, 40]
+
+    def test_window_size_consistency_with_small_overlap(self):
+        windows = split_windows(messages(100), 50, 1)
+        self.assertEqual(len(windows[0]), 50)
+        self.assertEqual(len(windows[1]), 50)
+        self.assertEqual(len(windows[-1]), 2)  # [0, 99]
+
 
 if __name__ == "__main__":
     unittest.main()
```