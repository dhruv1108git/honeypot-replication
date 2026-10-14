

After reviewing the entire commit chain, I found a critical off-by-one error in the reasoning truncation logic. The `truncate_thought` function in `sfttrain/templates.py` was incorrectly calculating the token slice, causing it to keep `max_tokens - 1` tokens instead of the intended `max_tokens` tokens. This bug would result in consistently shorter reasoning text than configured, potentially affecting model training quality.

The issue occurs in the slice calculation: `ids[len(ids) - max_tokens + 1:]` should be `ids[-max_tokens:]` to properly keep the last `max_tokens` tokens. The current implementation drops one extra token (e.g., with 100 tokens and max=10, it returns tokens 91-99 instead of 90-99).

I've verified this with the test case in `tests/test_templates.py` - the existing test only checked that truncation occurred but didn't verify the exact token count. I'm adding an assertion to confirm the correct number of tokens is preserved.

```diff
commit 3a8e1f0
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    templates: fix reasoning truncation to keep correct number of tokens
    
    The truncate_thought function was keeping max_tokens - 1 tokens instead of
    max_tokens due to an off-by-one error in the slice index. The function
    is supposed to keep the last `max_tokens` tokens of the reasoning, but
    was dropping one extra token.
    
    The bug occurred because the slice was `ids[len(ids) - max_tokens + 1:]`
    instead of `ids[-max_tokens:]` or `ids[len(ids) - max_tokens:]`.
    
    Also updates the test to verify the exact token count.

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..d9d5c66 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -75,7 +75,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..1b89b6c 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -32,10 +32,13 @@ class TemplateTests(unittest.TestCase):
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
         self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
         render(ex, "chat_v3", LocalTokenizer(), max_thought_tokens=100)
+        # Verify truncation happened to exactly 100 tokens
+        self.assertEqual(LocalTokenizer().count(ex.thought), 100)
         self.assertTrue(ex.thought_truncated)
 
     def test_unknown_role_raises(self):
```