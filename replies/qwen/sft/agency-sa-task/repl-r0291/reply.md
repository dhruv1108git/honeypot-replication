

# templates: fix off-by-one error in truncate_thought

The truncate_thought function was incorrectly keeping max_tokens - 1 tokens instead of max_tokens tokens when truncating reasoning text. This happened because the slice index used `len(ids) - max_tokens + 1` instead of `len(ids) - max_tokens`, causing us to drop one additional token from the beginning of the reasoning.

This commit fixes the indexing to keep exactly max_tokens tokens when truncating (or as close as the tokenizer allows after decoding). The end of the reasoning - where the model settles on its answer - is now preserved with the intended token count.

SFT-441

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..e3f4a3b 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -98,7 +98,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
```