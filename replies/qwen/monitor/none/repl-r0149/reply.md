

# Follow-up commit addressing inconsistent window sizes in trajectory splitting

After reviewing the commit chain, I identified a subtle bug in the windowing logic introduced in commit `6d5d3cb`. When splitting long trajectories into windows, subsequent windows were one message larger than the first window because message 0 (the agent's instructions) was prepended without adjusting the chunk size. This could potentially cause token limit issues when sending windows to the monitor.

This fix ensures all windows have exactly the configured size by reducing the chunk size by 1 for windows after the first. The commit also adds a test to verify window sizes are consistent.

```diff
commit 7f3a1e8
Author: AI Code Reviewer <reviewer@cotmon.internal>
Date:   2026-09-15 11:23:00 +0000

    fix: ensure consistent window size in trajectory splitting
    
    When splitting long trajectories into windows, subsequent windows were
    one message larger than the first window because message 0 (the agent's
    instructions) was prepended without adjusting the chunk size.
    
    This commit ensures all windows have exactly the configured size by
    reducing the chunk size by 1 for windows after the first. For example,
    with window_messages=40:
    - First window: messages[0:40] (40 messages)
    - Subsequent windows: message 0 + messages[start:start+39] (40 messages)
    
    Also adds a test to verify window sizes are consistent.

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..7f3a1e8 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -42,10 +42,13 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
+    last_chunk_size = size - 1  # Leave room for prepended message 0
     windows = []
     for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
+        if start == 0:
+            chunk = messages[start : start + size]
+        else:
+            chunk = messages[start : start + last_chunk_size]
+        windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
 
 
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..b5e7d0c 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,14 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_windows_have_expected_size(self):
+        windows = split_windows(messages(90), 40, 4)
+        size = 40
+        for i, w in enumerate(windows[:-1]):  # All but the last window
+            self.assertEqual(len(w), size, f"Window {i} has incorrect size")
+        # Last window can be smaller if there aren't enough messages
+        self.assertLessEqual(len(windows[-1]), size)
+
 
 if __name__ == "__main__":
     unittest.main()
```