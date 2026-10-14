

```diff
commit 9a8e5f1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    templates: fix reasoning truncation to keep exact token count
    
    The truncate_thought function had an off-by-one error that caused it to
    drop one token unnecessarily when truncating long reasoning text. The
    slice index used len(ids) - max_tokens + 1 instead of len(ids) - max_tokens,
    resulting in max_tokens - 1 tokens being kept instead of the requested
    count.
    
    This commit fixes the slice index and updates the test to verify the
    token count is as expected. The test now checks that the truncated text
    has exactly max_tokens tokens (or as close as possible when tokenization
    boundaries don't align perfectly).

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..5d4b796 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -95,7 +95,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..e2426f5 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -44,12 +44,19 @@ def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
         render(ex, "chat_v3", LocalTokenizer(), max_thought_tokens=100)
         self.assertTrue(ex.thought_truncated)
+        self.assertEqual(ex.n_tokens, 100)
 
     def test_unknown_role_raises(self):
         with self.assertRaises(ValueError):
             render(make_example(messages=[{"role": "tool", "content": "x"}]))
 
+    def test_truncation_keeps_exact_token_count(self):
+        tok = LocalTokenizer()
+        text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
+        cut_text, _ = truncate_thought(text, tok, 50)
+        self.assertEqual(tok.count(cut_text), 50)
+
 
 if __name__ == "__main__":
     unittest.main()
```