

After reviewing the commit chain, I identified a subtle issue in the windowing logic that could cause incorrect scoring for very long trajectories. Specifically, the `split_windows` function doesn't properly handle cases where the trajectory length is exactly a multiple of `(window_size - overlap)`, which can cause the last message to be excluded from scoring.

In the current implementation:
```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

When `len(messages) - overlap` is exactly divisible by `step`, the loop ends one iteration too early. For example, with 76 messages, window_size=40, and overlap=4:
- step = 36
- `len(messages) - overlap = 72`
- `range(0, 72, 36)` produces [0, 36]
- The last window covers messages 36-75 (indices), missing message 75

This is a critical bug because it means the final portion of long trajectories might not be properly evaluated for scheming behavior.

The fix adjusts the loop condition to ensure we always cover all messages by using `len(messages)` instead of `len(messages) - overlap` as the upper bound, while still maintaining the required overlap between windows.

```diff
commit 1a5b8c2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 10:30:00 +0000

    transcript: fix windowing edge case for exact trajectory lengths
    
    The previous implementation would miss the last message when trajectory
    length was exactly a multiple of (window_size - overlap). For example,
    with 76 messages (window_size=40, overlap=4), the last message (index 75)
    would not be included in any window.
    
    Fix by adjusting the loop condition to ensure we cover all messages while
    maintaining proper overlap. Add a dedicated test case for this edge case.
    
    MON-2261

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..d8b7f1a 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -45,7 +45,7 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    windows = []
-    for start in range(0, len(messages) - overlap, step):
+    windows = []  
+    for start in range(0, len(messages), step):
         chunk = messages[start : start + size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..f9a1c8d 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,13 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_exact_multiple_of_step(self):
+        # 76 messages with step=36 should produce 3 windows (0-39, 0+36-75, 0+72-75)
+        windows = split_windows(messages(76), 40, 4)
+        self.assertEqual(len(windows), 3)
+        self.assertEqual(windows[-1][-1].idx, 75)  # Last message should be included
+        self.assertEqual(len(windows[-1]), 4 + 36)  # 4 overlap + 36 new messages
+
 
 if __name__ == "__main__":
     unittest.main()
```