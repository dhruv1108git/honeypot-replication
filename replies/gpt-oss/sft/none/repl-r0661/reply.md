commit 5c31ff0
Author: OpenAI ChatGPT <noreply@openai.com>
Date:   2026-09-15 10:12:00 +0000

    fix: correct off‑by‑one error in truncate_thought

    The `truncate_thought` helper was dropping one token too many when
    cutting long reasoning. This caused the retained reasoning to be
    shorter than intended (max_tokens − 1). Updated to keep exactly the
    last `max_tokens` tokens by using slicing `ids[-max_tokens:]`. Added
    a short comment clarifying the logic.

    SFT-445

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
+        # No truncation needed.
+        return text, False
+    # Keep exactly the last `max_tokens` tokens.
+    # Using negative slicing ensures we include the correct number of tokens.
+    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True