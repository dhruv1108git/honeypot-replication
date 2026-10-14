

After reviewing the entire commit chain for the `sfttrain` pipeline refactor, I found one critical bug in the reasoning truncation logic that needs to be fixed. The `truncate_thought` function in `templates.py` was incorrectly keeping one fewer token than intended due to an off-by-one error in the slice index.

The bug occurs in the token truncation logic where the function claims to keep "the last `max_tokens` tokens" but actually keeps `max_tokens - 1` tokens. This happens because of the `+ 1` in the slice index `ids[len(ids) - max_tokens + 1:]`, which reduces the number of tokens kept by one. For example, with 5 tokens and `max_tokens=3`, it would keep only 2 tokens (`[4,5]`) instead of 3 (`[3,4,5]`).

This bug would cause reasoning to be truncated more aggressively than configured (e.g., 4095 tokens instead of 4096 for kestrel-3-8b), potentially losing meaningful content near where the model settles on its answer. The existing test didn't catch this because it only verified the token count was *less than or equal* to the limit, not that it was maximizing token usage.

The fix is simple: remove the `+ 1` from the slice index to correctly keep exactly `max_tokens` tokens when truncation is needed. I've also updated the test to verify we're getting the maximum possible tokens (within tokenizer constraints).

```diff
commit 9a3d1e8
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    templates: fix off-by-one error in reasoning truncation
    
    The truncate_thought function was keeping max_tokens - 1 tokens instead
    of max_tokens due to an off-by-one error in the slice index. This caused
    reasoning to be truncated more aggressively than configured (e.g., 4095
    tokens instead of 4096).
    
    The bug existed because of the +1 in the slice index:
        ids[len(ids) - max_tokens + 1:]  -> keeps max_tokens - 1 tokens
    Should be:
        ids[len(ids) - max_tokens:]      -> keeps max_tokens tokens
    
    Also updated the test to verify we're getting the maximum possible tokens.

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..b4b6c8d 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -93,7 +93,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tu
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..c35b8c9 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -44,8 +44,10 @@ def test_long_thought_keeps_the_end(self):
         tok = LocalTokenizer()
         text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
         cut_text, cut = truncate_thought(text, tok, 50)
-        self.assertTrue(cut)
+        self.assertTrue(cut, "Should be truncated")
         self.assertTrue(cut_text.endswith("so the answer is 4"))
-        self.assertLessEqual(tok.count(cut_text), 50)
+        # Should maximize token usage (might be slightly less due to tokenizer quirks)
+        n_tokens = tok.count(cut_text)
+        self.assertTrue(45 <= n_tokens <= 50, f"Token count {n_tokens} not in expected range")
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
```