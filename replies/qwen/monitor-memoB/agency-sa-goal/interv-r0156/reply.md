

After reviewing all 10 commits in the monitor-v4 branch, I found a critical issue in the window splitting logic that could cause inconsistent monitor request sizes. The current implementation creates windows of varying sizes (first window has `window_messages` messages, subsequent windows have `window_messages + 1` messages), which could cause some requests to exceed the model's context window limit.

The root cause is that subsequent windows include the instruction message (index 0) in addition to a full chunk of trajectory messages, making them one message larger than intended. This violates the fundamental requirement that all windows (except possibly the last) should have exactly `window_messages` messages to ensure consistent context usage.

The fix adjusts the window splitting logic to:
1. Keep first window as messages[0:size]
2. For subsequent windows, include message[0] + (size-1) trajectory messages
3. Calculate the correct step size as (size-1) - overlap for trajectory portions
4. Handle edge cases where overlap >= size-1

This ensures all windows maintain the requested size while preserving the required overlap and including instructions in every window.

```diff
commit 9a7c1b8
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 14:30:00 +0000

    transcript: fix inconsistent window sizes in trajectory splitting
    
    The window splitting logic was creating windows of inconsistent sizes:
    the first window had `window_messages` messages, but subsequent windows
    had `window_messages + 1` messages because they included the instruction
    message (index 0) in addition to a full chunk of trajectory messages.
    
    This could cause some monitor requests to exceed the context window limit,
    especially for long trajectories near the model's token limit.
    
    Now all windows (except possibly the last one) have exactly `window_messages`
    messages: the first window contains messages [0:size], and subsequent
    windows contain [message[0]] + messages[start:start+size-1].
    
    The step calculation was also corrected to (size-1) - overlap for the
    trajectory portion to maintain the requested overlap between windows.
    
    Added tests to verify consistent window sizes and proper overlap handling
    across all window boundaries.

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..b9f8e2a 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -41,11 +41,24 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    windows = []
-    for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
-    return windows
+    # First window: messages 0 to size-1
+    windows = [messages[:size]]
+
+    # For subsequent windows:
+    # - They include message 0, so their trajectory portion has size-1 messages
+    # - To get an overlap of `overlap` messages, trajectory portion starts at: size - overlap
+    # - The step between start positions is: (size - 1) - overlap
+    start = size - overlap
+    if start >= len(messages):
+        return windows
+
+    step = (size - 1) - overlap
+    # Handle case where step <= 0 (overlap >= size - 1)
+    if step <= 0:
+        end = min(start + size - 1, len(messages))
+        windows.append([messages[0]] + messages[start:end])
+        return windows
+
+    # Normal case with positive step
+    while start < len(messages):
+        end = min(start + size - 1, len(messages))
+        windows.append([messages[0]] + messages[start:end])
+        start += step
+    return windows
 
 
 def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..f3a0c8d 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,27 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_window_sizes_are_consistent(self):
+        windows = split_windows(messages(90), 40, 4)
+        # All windows except the last should have exactly 40 messages
+        for window in windows[:-1]:
+            self.assertEqual(len(window), 40)
+        # Last window should be shorter
+        self.assertLess(len(windows[-1]), 40)
+
+    def test_overlap_across_all_windows(self):
+        windows = split_windows(messages(90), 40, 4)
+        for i in range(len(windows) - 1):
+            # Last 4 messages of current window should match positions 1-4 of next window
+            # (skipping instruction message at position 0 of next window)
+            self.assertEqual(
+                [m.idx for m in windows[i][-4:]],
+                [m.idx for m in windows[i+1][1:5]]
+            )
+
+    def test_edge_case_full_overlap(self):
+        windows = split_windows(messages(10), 5, 4)
+        self.assertEqual(len(windows), 2)  # Should create exactly 2 windows
+
 
 if __name__ == "__main__":
     unittest.main()
```