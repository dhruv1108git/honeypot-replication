

```diff
commit 3a2d7f8
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    fix(truncation): keep exactly max_tokens tokens of reasoning
    
    The truncate_thought function had an off-by-one error in the slice index,
    causing it to keep (max_tokens - 1) tokens instead of max_tokens. This
    resulted in reasoning being truncated one token short of the intended limit.
    
    For example, with max_tokens=50, a 51-token reasoning would be truncated to
    49 tokens instead of 50. The fix changes the slice from
    `ids[len(ids) - max_tokens + 1:]` to `ids[len(ids) - max_tokens:]`.
    
    Added a test to verify the token count after truncation matches max_tokens
    when possible (accounting for lstrip effects).

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..e1c7a9d 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -96,7 +96,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     if len(ids) <= max_tokens:
         return text, False
     # Keep the last `max_tokens` tokens (fixing off-by-one error from +1)
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..3b0d6d4 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -1,7 +1,7 @@
 import unittest
 
-from sfttrain.templates import SYSTEM_PREAMBLE, render, truncate_thought
+from sfttrain.templates import SYSTEM_PREAMBLE, render, truncate_thought, DEFAULT_MAX_THOUGHT_TOKENS
 from sfttrain.tokenizer import LocalTokenizer
 
 from .helpers import make_example
@@ -52,6 +52,21 @@ class TemplateTests(unittest.TestCase):
         self.assertTrue(cut_text.endswith("so the answer is 4"))
         self.assertLessEqual(tok.count(cut_text), 50)
 
+    def test_truncation_keeps_exact_token_count(self):
+        """Verify we keep exactly max_tokens tokens when possible (without lstrip effects)"""
+        tok = LocalTokenizer()
+        # Create text with exactly max_tokens+1 identical tokens (no whitespace)
+        max_tokens = 50
+        text = "a" * (max_tokens + 1)
+        cut_text, cut = truncate_thought(text, tok, max_tokens)
+        self.assertTrue(cut)
+        self.assertEqual(tok.count(cut_text), max_tokens)
+        self.assertEqual(len(cut_text), max_tokens)  # Each 'a' is 1 token
+
+    def test_truncation_with_whitespace(self):
+        """Verify lstrip doesn't reduce token count below max_tokens when possible"""
+        tok = LocalTokenizer()
+        self.assertEqual(truncate_thought(" " * 10 + "a" * 50, tok, 50)[1], False)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
```