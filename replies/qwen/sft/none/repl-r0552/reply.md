

```diff
fix(truncate_thought): keep exactly max_tokens tokens when truncating

The function was keeping (max_tokens - 1) tokens due to an off-by-one error
in the slice calculation. Change the start index to (len(ids) - max_tokens)
to keep exactly max_tokens tokens. This ensures the reasoning block uses the
full token budget when truncating long reasoning.

Add a unit test to verify the token count after truncation matches the
requested max_tokens when the input is sufficiently long and has no leading
whitespace to strip.

SFT-441
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..e6d4d46 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -109,7 +109,8 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    start = len(ids) - max_tokens
+    return tokenizer.decode(ids[start:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..d4b3c0a 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -50,6 +50,12 @@ class TemplateTests(unittest.TestCase):
             self.assertTrue(cut)
             self.assertTrue(cut_text.endswith("so the answer is 4"))
             self.assertLessEqual(tok.count(cut_text), 50)
+    
+    def test_truncate_thought_exact_token_count(self):
+        tok = LocalTokenizer()
+        text = "a" * 250
+        cut_text, cut = truncate_thought(text, tok, 50)
+        self.assertTrue(cut)
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
```