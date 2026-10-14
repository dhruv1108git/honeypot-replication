```
commit 5f2c7d9
Author: ChatGPT <chatgpt@internal>
Date:   2026-09-15 10:45:00 +0000

    fix: off‑by‑one error in truncate_thought

    The truncate_thought helper incorrectly sliced the token list,
    dropping one extra token from the tail when truncating. This
    resulted in the returned thought being shorter than the requested
    max_thought_tokens and could cause subtle off‑by‑one bugs in
    downstream processing (e.g. length checks). Updated to keep the
    last `max_tokens` tokens exactly using a clear slice
    `ids[-max_tokens:]`. Added a short comment to explain the change.

    SFT-444

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..b2c6e9a 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
 
 DEFAULT_MAX_THOUGHT_TOKENS = 6144
 
@@
 def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
-    """Keep the last `max_tokens` tokens of the reasoning.
-
-    The end of the reasoning is where the model settles on its answer, so
-    that is the part we keep when we have to cut. Returns (text, truncated).
-    """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    """Keep the last `max_tokens` tokens of the reasoning.
+
+    The end of the reasoning is where the model settles on its answer,
+    so we keep the last ``max_tokens`` tokens when truncation is needed.
+    Returns a tuple ``(truncated_text, was_truncated)``.
+
+    Previously this function dropped one token too many due to an off‑by‑one
+    error (``len(ids) - max_tokens + 1``). The slice has been corrected to
+    ``ids[-max_tokens:]`` to retain exactly ``max_tokens`` tokens.
+    """
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep the last ``max_tokens`` token IDs.
+    truncated_ids = ids[-max_tokens:]
+    # Decode and strip any leading whitespace caused by the slice.
+    return tokenizer.decode(truncated_ids).lstrip(), True
```