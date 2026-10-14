commit 8a1d9c3
Author: ChatGPT <chatgpt@internal>
Date:   2026-09-15 10:22:31 +0000

    templates: fix off‑by‑one bug in truncate_thought

    The previous implementation dropped one token too many when truncating
    long reasoning texts: it sliced from `len(ids) - max_tokens + 1`,
    returning at most `max_tokens‑1` tokens. This could unnecessarily
    shorten useful reasoning and caused token‑count assertions to be
    less tight. The slice is now corrected to `len(ids) - max_tokens`,
    guaranteeing that the output contains at most `max_tokens` tokens
    while still keeping the end of the reasoning.

    Added a brief comment explaining the logic.

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..c9b1e2f 100644
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
+    # If the token count is within the limit, return unchanged.
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep exactly the last `max_tokens` tokens. The slice start index is
+    # `len(ids) - max_tokens`; using `+ 1` would drop one token too many.
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
