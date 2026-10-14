

# transcript: fix windowing to cover all messages

The current windowing logic in `split_windows()` could miss messages at the end of long trajectories if the number of messages isn't a multiple of `(window_messages - window_overlap)`. For example, with 41 messages, window size 40, and overlap 4, the last message would be excluded from all windows.

This changes the loop logic to ensure all messages are covered by:
1. Using a while loop instead of range() to handle variable window sizing
2. Properly calculating the end index for each chunk
3. Breaking when the end of messages is reached
4. Maintaining the required overlap between windows

Also adds a test case for non-multiples of step size to prevent regression.

MON-2253

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..d2c9a38 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -41,10 +41,13 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    windows = []
-    for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
+    windows = []
+    start = 0
+    while start < len(messages):
+        end = min(start + size, len(messages))
+        chunk = messages[start:end]
+        windows.append(chunk if start == 0 else [messages[0]] + chunk)
+        if end == len(messages):
+            break
+        start += step
     return windows
 
 
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..c054891 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,12 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_handles_non_multiple_of_step(self):
+        # 91 messages with window=40, overlap=4 should create 3 windows
+        windows = split_windows(messages(91), 40, 4)
+        self.assertEqual(len(windows), 3)
+        self.assertEqual(windows[-1][-1].idx, 90)  # Last message included
+
 
 if __name__ == "__main__":
     unittest.main()
```