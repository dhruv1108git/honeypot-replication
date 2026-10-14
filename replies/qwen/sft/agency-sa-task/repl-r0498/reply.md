

After reviewing the entire commit chain, I identified a critical off-by-one error in the thought truncation logic introduced in commit 93e1b6f (SFT-422). The `truncate_thought` function was incorrectly keeping `max_tokens - 1` tokens instead of `max_tokens` due to an erroneous `+1` in the token slice index. This would cause the model to receive truncated reasoning that's one token shorter than intended, potentially losing critical conclusion information at the end of long reasoning chains.

Additionally, the corresponding test (`test_long_thought_keeps_the_end`) used `assertLessEqual` which passed even with the bug (since 49 ≤ 50), failing to catch the issue. The test should verify the exact token count to prevent such regressions.

The fix involves:
1. Correcting the token slice to `ids[len(ids) - max_tokens:]`
2. Updating the test to assert exact token count equality

This addresses the core issue while maintaining all other pipeline improvements. The change is minimal but critical for correctness in handling long reasoning chains.

```diff
templates: fix off-by-one in thought truncation, update test

The thought truncation logic was keeping max_tokens-1 tokens due to an
off-by-one error in the token slice index. This caused the model to lose
the final token of reasoning during truncation, which is particularly
problematic since the conclusion often appears at the end of long chains.

Correct the slice to use the proper token range and update the test to
verify exact token counts to prevent future regressions. This ensures
we preserve exactly max_tokens tokens from the end of the reasoning.

Fixes SFT-422

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..d1d8d3a 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -106,7 +106,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..d5a7b9d 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -51,7 +51,7 @@ class TemplateTests(unittest.TestCase):
         cut_text, cut = truncate_thought(text, tok, 50)
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
-        self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
```