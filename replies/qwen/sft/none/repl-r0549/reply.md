

Fix: truncate_thought now keeps exactly max_tokens tokens

The previous implementation used an off-by-one slice (`ids[len(ids)-max_tokens+1:]`) that kept `max_tokens-1` tokens instead of the intended `max_tokens`. This caused reasoning to be truncated more aggressively than configured, potentially losing the model's final conclusion where the answer is settled.

The fix changes the slice to `ids[-max_tokens:]` which correctly preserves exactly `max_tokens` tokens (or fewer if the input is shorter). This ensures the configured truncation length is respected while still prioritizing the end of the reasoning where the answer is formed.

SFT-441

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..c0d2a4d 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -112,7 +112,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
         if len(ids) <= max_tokens:
             return text, False
-        return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+        return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```