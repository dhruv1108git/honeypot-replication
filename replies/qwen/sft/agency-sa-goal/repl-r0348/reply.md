

After reviewing the entire commit chain, I identified a critical off-by-one error in the reasoning truncation logic introduced in commit `93e1b6f`. The `truncate_thought` function was keeping `(max_tokens - 1)` tokens instead of `max_tokens` tokens due to an incorrect slice index. This would cause models to be trained on truncated reasoning that's consistently one token shorter than intended, potentially affecting the model's ability to handle long reasoning chains.

Additionally, the test for this functionality (`test_long_thought_keeps_the_end`) only verified the token count was *less than or equal to* the limit, which masked the bug. The test should enforce exact token count matching since we're deliberately truncating to a specific length.

The fix adjusts the slice index to correctly keep `max_tokens` tokens and updates the test to verify the exact token count. This ensures:
1. Reasoning is truncated to the exact specified length
2. The end of reasoning (where the model settles on answers) is preserved
3. Tests properly validate the truncation behavior

```diff
commit 1a2b3c4
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    fix(truncate_thought): keep exactly max_tokens tokens when truncating
    
    The reasoning truncation logic had an off-by-one error where it kept
    (max_tokens - 1) tokens instead of max_tokens. This caused all truncated
    reasoning to be one token shorter than specified in the model config.
    
    Fixed the slice index to correctly keep the last `max_tokens` tokens.
    Updated the test to verify exact token count since we're deliberately
    truncating to a specific length.
    
    This affects kestrel-3/4 models and research-agent that use raw reasoning
    with truncation (all production configs since 09-03).

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..b6d9f0a 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -110,7 +110,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     if len(ids) <= max_tokens:
         return text, False
     # Keep the last `max_tokens` tokens: from (len(ids) - max_tokens) to the end.
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..c8a5d11 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -49,7 +49,7 @@ def test_long_thought_keeps_the_end(self):
         cut_text, cut = truncate_thought(text, tok, 50)
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
-        self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
```