commit f9e2b9c8
Author: OpenAI ChatGPT <noreply@openai.com>
Date: 2026-09-15 15:42:10 +0000

    fix: correct off‑by‑one in truncate_thought to keep exactly max_thought_tokens

    The truncate_thought helper unintentionally dropped the first token of the retained
    slice, returning at most max_thought_tokens‑1 tokens. This could cause a
    short‑circuited reasoning block and subtle token‑count mismatches. Adjust the
    slice to include the full tail of the token list.

    Also tighten the docstring to reflect the exact behaviour.

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
+    # Return the last `max_tokens` token IDs, preserving the complete tail.
+    # The previous implementation used `len(ids) - max_tokens + 1`, which omitted
+    # one token from the retained slice (an off‑by‑one error).
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
