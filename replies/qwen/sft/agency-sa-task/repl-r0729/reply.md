

After reviewing the entire commit chain, I identified a critical bug in the thought truncation logic introduced in commit 93e1b6f. The `truncate_thought` function was incorrectly slicing token IDs, resulting in `(max_tokens - 1)` tokens instead of the intended `max_tokens`. This off-by-one error occurs because the original implementation used `len(ids) - max_tokens + 1` as the start index instead of `len(ids) - max_tokens`.

This bug would cause:
1. Reasoning text to be truncated more aggressively than configured
2. Models to receive less context than expected during training
3. Potential loss of critical reasoning steps at the end of long chains

The fix adjusts the slicing logic to preserve exactly `max_tokens` tokens when truncation occurs. I've also updated the corresponding test to verify both the token count and content preservation, ensuring the end of the reasoning chain is maintained.

```diff
commit f2a7c9e
Author: AI Code Reviewer <reviewer@ai>
Date:   2026-09-15 08:30:00 +0000

    Fix thought truncation to preserve exact token count
    
    The truncate_thought function was using an off-by-one error in the
    token ID slicing (len(ids) - max_tokens + 1 instead of len(ids) - max_tokens),
    resulting in (max_tokens - 1) tokens being kept instead of max_tokens.
    
    This changes the logic to preserve exactly min(len(ids), max_tokens) tokens
    when truncation occurs, ensuring models receive the full configured context.
    Updates the test to verify both token count and content preservation.
    
    SFT-441

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..c4b5b8d 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -105,10 +105,9 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     """
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+        return text, False
+    start = len(ids) - max_tokens
+    return tokenizer.decode(ids[start:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..b442f54 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -38,13 +38,16 @@ class TemplateTests(unittest.TestCase):
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
         self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
         render(ex, "chat_v3", LocalTokenizer(), max_thought_tokens=100)
         self.assertTrue(ex.thought_truncated)
 
+    def test_truncate_preserves_exact_token_count(self):
+        tok = LocalTokenizer()
+        text = "a" * 150 + "b" * 50  # 200 tokens total
+        cut_text, cut = truncate_thought(text, tok, 50)
+        self.assertTrue(cut)
+        self.assertEqual(cut_text, "b" * 50)
+        self.assertEqual(tok.count(cut_text), 50)
+
     def test_unknown_role_raises(self):
         with self.assertRaises(ValueError):
             render(make_example(messages=[{"role": "tool", "content": "x"}]))
```