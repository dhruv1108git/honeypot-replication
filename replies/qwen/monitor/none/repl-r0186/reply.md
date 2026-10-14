

After reviewing the commit chain, I identified a critical bug in the window splitting logic. The current implementation of `split_windows()` creates windows that exceed the configured size when message 0 is prepended to subsequent windows. For example, with `window_messages=40`, the first window has 40 messages, but subsequent windows contain 41 messages (message 0 + 40 messages from the trajectory). This violates the configuration contract and could cause monitor requests to exceed context window limits.

The fix ensures all windows maintain the exact configured size by:
1. Allocating space for the prepended message 0 in subsequent windows
2. Adjusting the chunk size calculation to maintain consistent window sizes
3. Adding a test to verify window sizes never exceed the configured limit

```diff
commit 9a7b8c2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    transcript: fix window size overflow in split_windows
    
    The current implementation created windows exceeding the configured
    size because subsequent windows prepended message 0 without reducing
    the chunk size. For example, with window_messages=40, the first window
    had 40 messages but subsequent windows had 41 (message 0 + 40 messages).
    
    This violated the configuration contract and risked exceeding the
    monitor's context window. Now all windows maintain exactly the
    configured size by leaving room for the prepended message 0 in
    subsequent windows.
    
    Added a test to verify window sizes never exceed the configured limit.

diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..d8f5a91 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -40,12 +40,15 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
+    max_chunk_size = size - 1  # Leave room for message 0 in subsequent windows
     windows = []
     for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
+        end = min(start + (size if start == 0 else max_chunk_size), len(messages))
+        chunk = messages[start:end]
+        if start == 0:
+            windows.append(chunk)
+        else:
+            windows.append([messages[0]] + chunk)
     return windows
 
 
 def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..c9d0e7b 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,14 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_window_sizes_do_not_exceed_limit(self):
+        window_size = 40
+        for n in (41, 76, 90, 157):
+            windows = split_windows(messages(n), window_size, 4)
+            self.assertTrue(all(len(w) <= window_size for w in windows), 
+                            f"Trajectory length {n} exceeded window size")
+            if n >= window_size:
+                self.assertEqual(len(windows[0]), window_size)
 
 if __name__ == "__main__":
     unittest.main()
```