

```diff
commit 8a7c9f2
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    fix(truncate_thought): truncate to exactly max_tokens tokens
    
    The truncate_thought function had an off-by-one error in the token slice,
    resulting in reasoning being truncated to (max_tokens - 1) tokens instead
    of max_tokens. This wasted valuable token budget for the reasoning portion
    of the target sequence.
    
    Changed the slice from `ids[len(ids) - max_tokens + 1:]` to `ids[-max_tokens:]`
    to correctly keep the last `max_tokens` tokens. Updated the test to verify
    the exact token count after truncation.
    
    This affects all models using thought truncation (kestrel-3/4 and research-agent),
    ensuring they utilize the full configured reasoning token budget.

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..e8c59c0 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -93,7 +93,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     if len(ids) <= max_tokens:
         return text, False
     return tokenizer.decode(
-        ids[len(ids) - max_tokens + 1:]
+        ids[-max_tokens:]
     ).lstrip(), True
 
 
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..d3a2c10 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -48,7 +48,8 @@ def test_long_thought_keeps_the_end(self):
         tok = LocalTokenizer()
         text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
         cut_text, cut = truncate_thought(text, tok, 50)
-        self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertTrue(cut)
+        self.assertEqual(tok.count(cut_text), 50)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
 
     def test_render_marks_truncation(self):
```