

After analyzing the commit chain, I identified a critical bug in the windowing logic for trajectory processing. The current implementation in `split_windows()` uses `range(0, len(messages) - overlap, step)` which can miss the final messages when trajectory length isn't perfectly aligned with window size and overlap.

For example, with 80 messages, window size 40, and overlap 4:
- Current code: `range(0, 76, 36)` → windows at [0, 36]
- Misses messages 76-79 (last 4 messages)
- Correct behavior should include a third window starting at 72

This bug could cause parts of agent trajectories to be unreviewed, potentially missing critical scheming behavior. The fix is to change the range to `range(0, len(messages), step)` while maintaining proper window boundaries.

I've also added a test case for trajectory length 80 to verify the fix, as the existing tests didn't cover this edge case.

```diff
commit 8a3c1e9
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:23:47 +0000

    transcript: fix windowing logic to cover all messages
    
    The current implementation could miss messages at the end of trajectories
    when the length isn't perfectly divisible by (window_size - overlap).
    For example, with 80 messages, window_size=40, and overlap=4, the last
    4 messages would be missed.
    
    Changes the range condition from `len(messages) - overlap` to
    `len(messages)` to ensure all messages are covered, while maintaining
    the required overlap between windows.
    
    Adds a test case for trajectory length 80 to verify coverage.

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..f5d1b2a 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -44,7 +44,7 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    windows = []
-    for start in range(0, len(messages) - overlap, step):
+    windows = []
+    # Process all messages by iterating to len(messages) (not len - overlap)
+    for start in range(0, len(messages), step):
         chunk = messages[start : start + size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..d7b8c9f 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -25,6 +25,9 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertEqual([m.idx for m in first[-4:]], [m.idx for m in second[1:5]])
 
+    def test_handles_trajectory_length_not_divisible_by_step(self):
+        self.assertEqual(len(split_windows(messages(80), 40, 4)), 3)
+
     def test_later_windows_start_with_instructions(self):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
```