backends/truncate_thought: fix off‑by‑one bug and simplify logic

The `truncate_thought` helper incorrectly sliced the token list, dropping one token too many
(`ids[len(ids) - max_tokens + 1:]`). This caused the truncated reasoning to be shorter than
requested and could lead to unexpected token counts. The implementation is updated to use a
clearer slice (`ids[-max_tokens:]`) that reliably keeps exactly `max_tokens` tokens from the
end of the reasoning. The function now returns the decoded text with leading whitespace stripped
as before, and the documentation comment remains unchanged.

```diff
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
 def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
     """Keep the last `max_tokens` tokens of the reasoning.
 
     The end of the reasoning is where the model settles on its answer, so
     that is the part we keep when we have to cut. Returns (text, truncated).
     """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep exactly the last `max_tokens` token IDs.
+    truncated_ids = ids[-max_tokens:]
+    return tokenizer.decode(truncated_ids).lstrip(), True
```