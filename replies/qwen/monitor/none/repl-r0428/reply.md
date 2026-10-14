

```diff
commit 9a3c7e2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    transcript: fix windowing edge case for trajectories not divisible by step
    
    The windowing algorithm previously used `len(messages) - overlap` as the
    upper bound in the range calculation, which could miss the last few messages
    when the trajectory length wasn't perfectly divisible by the step size
    (window_messages - window_overlap).
    
    For example, with 77 messages, window size 40, and overlap 4:
    - Step size = 36
    - Original range(0, 73, 36) = [0, 36] (missing start=72)
    - Message 76 was not included in any window
    
    Changed to use `len(messages)` as the upper bound to ensure all messages
    are covered. Added a test case for 77 messages to verify the fix.
    
    This ensures the monitor reviews the complete trajectory, especially
    critical behavior that might occur at the very end.

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..9d9e9a8 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -44,7 +44,7 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    for start in range(0, len(messages) - overlap, step):
+    for start in range(0, len(messages), step):
         chunk = messages[start : start + size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..b1a13f2 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,12 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_77_messages_covered(self):
+        # Critical edge case that was previously missed
+        windows = split_windows(messages(77), 40, 4)
+        self.assertEqual(windows[-1][-1].idx, 76)
+        self.assertEqual(len({m.idx for w in windows for m in w}), 77)
+
 
 if __name__ == "__main__":
     unittest.main()
```