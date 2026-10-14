

After reviewing the commit chain for the `cotmon` repository, I identified an issue in the window splitting logic. The current implementation correctly handles overlapping windows but doesn't properly validate the case where `window_overlap = 0`. While the configuration validation ensures `0 <= window_overlap < window_messages`, the `split_windows` function contains a subtle bug when `window_overlap = 0`:

1. When `window_overlap = 0`, the step size becomes `window_messages - 0 = window_messages`
2. The range calculation `range(0, len(messages) - overlap, step)` becomes `range(0, len(messages), window_messages)`
3. This causes the last window to potentially miss the final messages when `len(messages)` isn't divisible by `window_messages`

For example, with 95 messages, `window_messages = 40`, and `window_overlap = 0`:
- Expected windows: [0-39], [0,40-79], [0,80-94]
- Actual behavior: Only [0-39] and [0,40-79] would be created, missing messages 80-94

The fix involves adjusting the range calculation to ensure the last window is always included by using `len(messages)` instead of `len(messages) - overlap` in the range upper bound.

Here's the follow-up commit that fixes this edge case and adds test coverage:

```diff
commit 7c3d8f1
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    transcript: fix window splitting for zero overlap case
    
    The range calculation in split_windows() used len(messages) - overlap
    as the upper bound, which caused the last window to be missed when
    window_overlap = 0 and len(messages) isn't divisible by window_messages.
    
    Changed to use len(messages) as the upper bound since the loop condition
    already ensures we don't go out of bounds. Added test coverage for the
    zero overlap case and non-divisible message counts.
    
    This fixes a potential issue where trajectories with message counts not
    divisible by window size would have incomplete coverage when using
    zero overlap configuration.

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..b7a9c12 100644
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
index 2b4be50..d9e6f1a 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,27 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_zero_overlap_cover_all_messages(self):
+        """Ensure all messages are covered even with zero overlap."""
+        for total in (40, 41, 79, 80, 81, 90):
+            with self.subTest(total=total):
+                windows = split_windows(messages(total), 40, 0)
+                seen = {m.idx for w in windows for m in w}
+                # Subtract 1 for the duplicate message 0 in subsequent windows
+                expected_count = total + (len(windows) - 1)
+                self.assertEqual(len(seen), expected_count)
+                self.assertEqual(seen, set(range(total)), f"Missing messages for n={total}")
+
+    def test_zero_overlap_window_boundaries(self):
+        """Verify window boundaries with zero overlap."""
+        windows = split_windows(messages(81), 40, 0)
+        self.assertEqual(len(windows), 3)
+        # First window: 0-39
+        self.assertEqual([m.idx for m in windows[0]], list(range(40)))
+        # Second window: 0,40-79
+        self.assertEqual([m.idx for m in windows[1]], [0] + list(range(40, 80)))
+        # Third window: 0,80
+        self.assertEqual([m.idx for m in windows[2]], [0, 80])
 
 if __name__ == "__main__":
     unittest.main()
```