

# transcript: clarify windowing behavior in docstrings

The windowing logic in split_windows() has subtle behavior around message 0
(the instructions) that could be confusing to maintainers. Add detailed
examples to the docstring to explain how windows are constructed and why
the first window is treated differently.

Also fix a minor typo in the docstring ("Consecutive windows share
``overlap`` messages" -> "Consecutive windows share up to ``overlap``
messages").

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..1d76b58 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -27,12 +27,27 @@ def render_window(messages: list[Message], include_raw_reasoning: bool = True) -
     return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
 
 
-def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
-    """Split a message list into windows of ``size`` messages.
+def split_windows(
+    messages: list[Message], size: int, overlap: int
+) -> list[list[Message]]:
+    """Split a message list into windows of ``size`` messages with overlap.
 
-    Consecutive windows share ``overlap`` messages so that an exchange on a
-    window boundary is seen in full at least once. Every window after the first
-    also starts with message 0 (the agent's instructions) so the monitor knows
-    what task the agent was given.
+    Consecutive windows share up to ``overlap`` messages so that an exchange on
+    a window boundary is seen in full at least once. Every window after the
+    first also starts with message 0 (the agent's instructions) so the monitor
+    knows what task the agent was given, even if the window doesn't include
+    the original instructions message.
+
+    Example with size=5, overlap=2, and 10 messages [0,1,2,3,4,5,6,7,8,9]:
+      Window 1: [0,1,2,3,4]  (original first 5 messages)
+      Window 2: [0,4,5,6,7]  (instructions + messages 4-7, sharing [4] with Window 1)
+      Window 3: [0,7,8,9]    (instructions + messages 7-9, sharing [7] with Window 2)
+
+    Note that Window 1 already contains the instructions (message 0), so we
+    don't add another copy. Subsequent windows add message 0 at the beginning,
+    which means they have the same number of messages from the original
+    trajectory plus one extra (message 0). This slight size difference is
+    acceptable as token limits are approximate and message 0 is typically small.
 
     """
     if len(messages) <= size:
```