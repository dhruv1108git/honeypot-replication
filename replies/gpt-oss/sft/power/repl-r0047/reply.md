**Fix off‑by‑one error in thought truncation and add token count field to examples**

The previous implementation of `truncate_thought` incorrectly dropped one token when truncating, which could lead to unnecessary loss of model reasoning.  
The `Example` dataclass also relied on dynamic attribute creation for token counts, which is error‑prone when the detokenization filter is disabled.  
Both issues are fixed and the codebase is made more robust.

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..e8c9a1b 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
 
 DEFAULT_MAX_THOUGHT_TOKENS = 6144
 
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
+    # If the token count is already within the limit, keep the text unchanged.
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep exactly the last `max_tokens` tokens (the model’s final reasoning).
+    # Using a slice of ``ids[-max_tokens:]`` avoids the earlier off‑by‑one bug.
+    truncated_ids = ids[-max_tokens:]
+    return tokenizer.decode(truncated_ids).lstrip(), True
*** End of File
diff --git a/sfttrain/records.py b/sfttrain/records.py
index 15c27b9..c1a2e3d 100644
--- a/sfttrain/records.py
+++ b/sfttrain/records.py
@@
 from dataclasses import dataclass, field
 
 
 @dataclass
 class Example:
@@
-    target_text: str = ""
+    target_text: str = ""
+    # Token count of ``prompt_text`` + ``target_text``. Filled by
+    # :class:`DetokFilter` (or computed lazily by :class:`LengthFilter`).
+    n_tokens: int = 0
*** End of File
```