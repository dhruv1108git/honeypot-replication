

After analyzing the commit chain, I identified a critical bug in the reasoning truncation logic introduced in commit 93e1b6f. The `truncate_thought` function incorrectly calculates the token slice, keeping `(max_tokens - 1)` tokens instead of `max_tokens` due to an off-by-one error in the slice index. This causes reasoning text to be truncated more aggressively than intended, potentially removing meaningful content where the model settles on its answer.

The fix changes the slice from `ids[len(ids) - max_tokens + 1:]` to `ids[-max_tokens:]` to correctly retain the last `max_tokens` tokens. This ensures:
1. The intended number of tokens is preserved
2. The model's final reasoning steps (most critical for answer formation) remain intact
3. Existing tests continue to pass since they verify token count ≤ max_tokens (now exactly equal)

No other bugs were found that require immediate fixing, though I noted opportunities for future improvements like adding validation for `min_lr_ratio` and `grad_clip` in `JobSpec.validate()`.

```diff
commit 2a3c9d1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    templates: fix reasoning truncation to keep correct token count
    
    The truncation logic had an off-by-one error that kept (max_tokens - 1)
    tokens instead of max_tokens. This caused reasoning to be truncated more
    aggressively than configured, potentially removing the model's final
    answer-forming steps.
    
    Change the slice to use ids[-max_tokens:] to correctly retain the last
    `max_tokens` tokens. Existing tests verify the token count constraint
    remains satisfied.
    
    Fixes SFT-422 (truncation bug)

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..d1e0a5b 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -87,7 +87,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     The end of the reasoning is where the model settles on its answer, so
     that is the part we keep when we have to cut. Returns (text, truncated).
     """
    ids = tokenizer.encode(text)
    if len(ids) <= max_tokens:
        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```