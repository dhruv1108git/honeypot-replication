

# transcript: fix windowing to cover all trajectory messages

The `split_windows()` function used a loop condition that could miss the last message(s) of a trajectory. For example, with 77 messages, window size 40 and overlap 4, message 76 would not be included in any window. This would cause the monitor to miss potentially critical behavior at the very end of long episodes.

Change the loop condition to `range(0, len(messages), step)` to ensure all messages are covered in at least one window. The existing test `test_windows_cover_every_message` already verifies this property, so no additional tests are needed.

MON-2260

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..b8c8b04 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -47,7 +47,7 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    for start in range(0, len(messages) - overlap, step):
+    for start in range(0, len(messages), step):
         chunk = messages[start : start + size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
```