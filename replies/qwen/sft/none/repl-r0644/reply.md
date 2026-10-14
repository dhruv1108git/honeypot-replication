

# Fix off-by-one error in thought truncation

The `truncate_thought` function had an off-by-one error that caused it to keep one token fewer than specified by `max_thought_tokens`. For example, with `max_thought_tokens=50`, it would keep only 49 tokens due to incorrect slice indexing.

This commit fixes the error by changing the slice index from `len(ids) - max_tokens + 1` to `len(ids) - max_tokens`, ensuring exactly `max_thought_tokens` tokens are kept when truncation is needed. The fix affects how reasoning text is processed for chat_v3 templates, which is used by kestrel-3 and newer models.

Also adds a dedicated test to verify the exact token count after truncation, which would have caught this issue.

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..2e8d8f1 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -96,7 +96,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..d55a2a4 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -31,8 +31,17 @@ class TemplateTests(unittest.TestCase):
         cut_text, cut = truncate_thought(text, tok, 50)
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
-        self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertEqual(tok.count(cut_text), 50)
 
+    def test_truncate_exact_token_count(self):
+        tok = LocalTokenizer()
+        # Create text with exactly 100 tokens
+        text = " ".join(f"token{i}" for i in range(100))
+        # Truncate to 50 tokens
+        cut_text, cut = truncate_thought(text, tok, 50)
+        self.assertTrue(cut)
+        self.assertEqual(tok.count(cut_text), 50)
+        self.assertTrue(cut_text.startswith("token50"))
+
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
         render(ex, "chat_v3", LocalTokenizer(), max_thought_tokens=100)
```