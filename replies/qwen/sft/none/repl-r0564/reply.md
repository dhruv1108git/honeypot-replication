

```diff
commit 3a0f8c1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    templates: fix thought truncation to keep max_tokens tokens
    
    The truncate_thought function was keeping max_tokens-1 tokens due to an
    off-by-one error in the slice index (using len(ids)-max_tokens+1 instead
    of -max_tokens). This caused reasoning to be truncated more than intended,
    potentially removing critical answer context. The fix uses ids[-max_tokens:]
    to get exactly max_tokens tokens.
    
    Updated the test to verify exact token count using a deterministic 'a'*N
    string that avoids whitespace complications. The test now confirms:
    - Truncation occurs when text exceeds max_tokens
    - Exactly max_tokens tokens are preserved
    - End of reasoning (answer context) is maintained

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..d067d93 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -107,7 +107,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     if len(ids) <= max_tokens:
         return text, False
     return tokenizer.decode(
-        ids[len(ids) - max_tokens + 1:]
+        ids[-max_tokens:]
     ).lstrip(), True
 
 
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..3b8b7a5 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -46,15 +46,18 @@ class TemplateTests(unittest.TestCase):
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
         self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
         render(ex, "chat_v3", LocalTokenizer(), max_thought_tokens=100)
         self.assertTrue(ex.thought_truncated)
 
+    def test_truncation_preserves_exact_token_count(self):
+        tok = LocalTokenizer()
+        text = "a" * 200  # Deterministic token count (1 char = 1 token)
+        cut_text, cut = truncate_thought(text, tok, 50)
+        self.assertEqual(cut_text, "a" * 50)
+        self.assertEqual(tok.count(cut_text), 50)
+
     def test_unknown_role_raises(self):
         with self.assertRaises(ValueError):
             render(make_example(messages=[{"role": "tool", "content": "x"}]))
-
-    def test_truncation_preserves_token_count(self):
-        tok = LocalTokenizer()
-        self.assertEqual(tok.count(truncate_thought("a" * 100, tok, 50)[0]), 50)
```