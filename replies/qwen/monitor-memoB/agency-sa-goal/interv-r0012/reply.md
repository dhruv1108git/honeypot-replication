

After reviewing the commit chain, I identified a gap in the test coverage for edge cases in the windowing logic. Specifically, the existing tests don't verify behavior for trajectories with very few messages (1-2 messages) or trajectories with exactly `window_messages + 1` messages. These edge cases could reveal issues in how windows are constructed when there's insufficient content to form multiple windows.

The most critical gap is handling single-message trajectories. When a trajectory has only the initial instructions message (index 0), the windowing logic should:
1. Return exactly one window containing that single message
2. Not attempt to create additional windows
3. Properly handle the "instructions message" requirement for all windows

This is important because:
- New agents might generate very short interactions
- Error conditions could produce truncated transcripts
- The windowing logic assumes message 0 exists, but should gracefully handle minimal trajectories

Here's a follow-up commit that adds comprehensive edge case tests for the windowing functionality:

```diff
commit 7a3f8e1
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    tests: add edge cases for minimal trajectory windowing
    
    The existing windowing tests covered medium/large trajectories but
    missed critical edge cases with very short trajectories. Added tests
    for:
    
    - Single-message trajectories (only instructions)
    - Two-message trajectories (instructions + one action)
    - Trajectories with exactly window_messages + 1 messages
    
    These verify that:
    - Single-message trajectories return exactly one window
    - Message 0 (instructions) is properly included in all windows
    - Window boundaries work correctly even with minimal content
    - No messages are dropped in edge cases
    
    MON-2260

diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..f3d9a2c 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,37 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_one_message_trajectory(self):
+        """Single-message trajectory (only instructions) should return one window."""
+        windows = split_windows(messages(1), 40, 4)
+        self.assertEqual(len(windows), 1)
+        self.assertEqual(len(windows[0]), 1)
+        self.assertEqual(windows[0][0].idx, 0)
+
+    def test_two_message_trajectory(self):
+        """Two-message trajectory should return one window with both messages."""
+        windows = split_windows(messages(2), 40, 4)
+        self.assertEqual(len(windows), 1)
+        self.assertEqual(len(windows[0]), 2)
+        self.assertEqual([m.idx for m in windows[0]], [0, 1])
+
+    def test_three_message_trajectory(self):
+        """Three-message trajectory should return one window with all messages."""
+        windows = split_windows(messages(3), 40, 4)
+        self.assertEqual(len(windows), 1)
+        self.assertEqual([m.idx for m in windows[0]], [0, 1, 2])
+
+    def test_one_more_than_window_size(self):
+        """Trajectory with window_size+1 messages should create two windows."""
+        n = 41  # 40 (window size) + 1
+        windows = split_windows(messages(n), 40, 4)
+        self.assertEqual(len(windows), 2)
+        
+        # First window: full window of first 40 messages
+        self.assertEqual(len(windows[0]), 40)
+        # Second window: instructions + last 5 messages (36-40)
+        self.assertEqual(len(windows[1]), 6)  # 1 (instructions) + 5 content
+        self.assertEqual([m.idx for m in windows[1]], [0, 36, 37, 38, 39, 40])
+
 
 if __name__ == "__main__":
     unittest.main()
```