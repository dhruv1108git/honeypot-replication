**Commit message:**
Fix off‑by‑one error in thought truncation logic

The tokenizer works at a character‑level, so truncating a reasoning
string must keep the *last* `max_tokens` characters.  The previous
implementation started the slice one token too far, dropping an extra
character and potentially cutting off the end of the reasoning.  This
breaks the guarantee that the truncated text always ends with the
original tail (e.g. “so the answer is 4”).  The fix corrects the slice
to include the exact last `max_tokens` tokens.

**Patch:**
```diff
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
-def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
-    """Keep the last `max_tokens` tokens of the reasoning.
-
-    The end of the reasoning is where the model settles on its answer, so
-    that is the part we keep when we have to cut. Returns (text, truncated).
-    """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
+    """Keep the last `max_tokens` tokens of the reasoning.
+
+    The end of the reasoning is where the model settles on its answer, so
+    that is the part we keep when we have to cut. Returns (text, truncated).
+    """
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        # The whole reasoning fits.
+        return text, False
+    # Keep the final `max_tokens` token ids.
+    truncated_ids = ids[-max_tokens:]
+    # Decode and strip any leading whitespace introduced by the slice.
+    return tokenizer.decode(truncated_ids).lstrip(), True
```