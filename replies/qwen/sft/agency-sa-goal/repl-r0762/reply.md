

After reviewing the commit chain, I found a critical bug in the `truncate_thought` function introduced in commit 93e1b6f. The implementation incorrectly kept `max_tokens - 1` tokens due to an off-by-one error in the token slice calculation. Additionally, the `.lstrip()` call was removing leading space tokens that are part of the model's output, which could alter the training data.

The fix involves:
1. Correcting the token slice to keep exactly `max_tokens` tokens
2. Removing `.lstrip()` to preserve the original token sequence
3. Updating the test to verify exact token count instead of upper bound

This ensures reasoning truncation works as documented ("keep the last `max_tokens` tokens") and maintains data integrity for training.

```diff
commit 8a1b2c3
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    fix: truncate_thought keeps exact token count and preserves leading spaces
    
    The previous implementation kept max_tokens-1 tokens due to off-by-one error
    in token slice calculation. Also removed .lstrip() which was removing valid
    space tokens from model output. Updated test to verify exact token count.
    
    Fixes SFT-441

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..d0a8e5c 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -98,10 +98,11 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     """
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+        return text, False
+    start = len(ids) - max_tokens
+    truncated_text = tokenizer.decode(ids[start:])
+    return truncated_text, True
 
-
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
            max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:
     t = get_template(template)
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..d0a8e5c 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -47,7 +47,7 @@ def test_long_thought_keeps_the_end(self):
         cut_text, cut = truncate_thought(text, tok, 50)
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
-        self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
```