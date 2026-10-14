

After reviewing the entire commit chain, I identified a critical bug in the reasoning truncation logic introduced in commit 93e1b6f. The `truncate_thought` function incorrectly keeps `max_tokens - 1` tokens instead of `max_tokens` due to an off-by-one error in the slice calculation. This causes reasoning to be truncated one token short of the configured limit, which could lead to incomplete reasoning being presented to the model during training.

The bug occurs in this line:
```python
return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
```

The correct implementation should use:
```python
return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
```

This fix ensures we keep exactly `max_tokens` tokens from the end of the reasoning text. I've verified that the existing unit test still passes with this correction (it already checks token count is ≤ max_tokens, which remains valid since `lstrip()` might reduce the count by at most 1 token).

```diff
commit 8a7b9c0
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    templates: fix reasoning truncation to keep max_tokens tokens
    
    The previous implementation kept max_tokens - 1 tokens because it used
    `ids[len(ids) - max_tokens + 1:]` instead of `ids[len(ids) - max_tokens:]`.
    This caused reasoning to be truncated one token short of the limit.
    
    The unit test now checks that the truncated text has at most max_tokens
    tokens (as before) but the token count should be exactly max_tokens unless
    lstrip removes leading whitespace tokens.
    
    SFT-441

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..d4c8f0a 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -95,7 +95,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     if len(ids) <= max_tokens:
         return text, False
     # Keep the last `max_tokens` tokens: from index (len(ids) - max_tokens) to the end.
-    truncated_ids = ids[len(ids) - max_tokens + 1:]
+    truncated_ids = ids[len(ids) - max_tokens:]
     return tokenizer.decode(truncated_ids).lstrip(), True
 
 
```