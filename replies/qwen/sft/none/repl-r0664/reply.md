

templates: fix off-by-one error in reasoning truncation

The truncate_thought function was using an incorrect slice index when keeping the
last `max_tokens` tokens of reasoning text. The original implementation used
`len(ids) - max_tokens + 1` as the start index, which resulted in keeping
`max_tokens - 1` tokens instead of the intended `max_tokens` tokens.

This caused reasoning to be truncated more aggressively than configured, potentially
dropping important concluding steps that the model uses to formulate its answer.
The fix changes the start index to `len(ids) - max_tokens`, ensuring exactly
`max_tokens` tokens are preserved from the end of the reasoning text.

The issue affected all models using `thought_source = "raw"` with reasoning longer
than `max_thought_tokens`, including kestrel-3 and kestrel-4 models. The fix
ensures the configured token limit is respected while preserving the most
critical parts of the reasoning.

Fixes SFT-422 (truncation bug).

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..a1b3c4d 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -110,7 +110,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tu
         if len(ids) <= max_tokens:
             return text, False
-        return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+        return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
```