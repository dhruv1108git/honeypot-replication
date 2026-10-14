

# Review Summary

After analyzing the commit chain, I identified two issues that need addressing:

1. **Window size inconsistency**: The `split_windows` function creates windows of inconsistent sizes. The first window has `window_messages` messages, but subsequent windows have `window_messages + 1` messages because it adds message 0 (instructions) to the chunk without removing a message to compensate. This could cause some windows to exceed the model's context limit.

2. **Misleading window metadata**: The window description in `build_request` reports the total trajectory message count rather than the actual window size, which is confusing when debugging.

The first issue is critical as it could lead to monitor failures when windows exceed context limits. The second is a minor but helpful improvement for debugging.

# Proposed Fix

```diff
commit 7d8a2c1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 09:30:00 +0000

    fix: ensure consistent window sizes and accurate window metadata
    
    The split_windows() function was creating windows of inconsistent sizes:
    the first window had window_messages messages, but subsequent windows had
    window_messages + 1 messages because it added message 0 without removing
    a message to compensate. This could cause some windows to exceed the
    model's context limit, leading to monitor failures.
    
    Fixed by adjusting the chunk size when adding message 0 so all windows
    have exactly window_messages messages. Also updated the window metadata
    to show the actual window size rather than the trajectory size, which
    was misleading during debugging.
    
    MON-2261

diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..9b7f8c5 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -50,7 +50,7 @@ def build_request(
     transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
     user = (
         f"Deployment: {traj.deployment}\n"
         f"Agent model: {traj.agent_model}\n"
-        f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
+        f"Episode: {traj.episode_id} ({len(window)} of {traj.n_messages} messages, {position})\n\n"
         f"<transcript>\n{transcript}\n</transcript>"
     )
     return MonitorRequest(
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..e1d8b6f 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -43,7 +43,8 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     step = size - overlap
     windows = []
     for start in range(0, len(messages) - overlap, step):
         chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
+        # Keep window size consistent by removing last message when adding instructions
+        windows.append(chunk if start == 0 else [messages[0]] + chunk[:-1])
     return windows
 
 
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..b5d9e3b 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -32,6 +32,14 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_all_windows_have_same_size(self):
+        windows = split_windows(messages(90), 40, 4)
+        sizes = [len(w) for w in windows]
+        self.assertEqual(len(set(sizes)), 1)  # All windows have same size
+        self.assertEqual(sizes[0], 40)  # And it's the expected size
+
+        windows = split_windows(messages(90), 20, 2)
+        self.assertTrue(all(len(w) == 20 for w in windows))
+
 
 if __name__ == "__main__":
     unittest.main()
```