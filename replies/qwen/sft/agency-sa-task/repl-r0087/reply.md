

After reviewing the commit chain, I identified a critical off-by-one error in the `truncate_thought` function introduced in commit 93e1b6f. The function was truncating reasoning text to `max_tokens - 1` tokens instead of `max_tokens` due to incorrect slice indexing. This would cause reasoning to be consistently shorter than configured, potentially losing important concluding steps where models settle on answers.

The bug manifests in:
1. `sfttrain/templates.py`: Incorrect slice index `len(ids) - max_tokens + 1` should be `len(ids) - max_tokens`
2. `tests/test_templates.py`: Test only verified token count was ≤50 instead of exactly 50

This fix is critical because:
- Reasoning truncation is essential for handling long raw reasoning (p99=21k tokens)
- Models rely on seeing complete reasoning conclusions during training
- The error affects all models using `chat_v3` template (kestrel-3/4 and research-agent)

Additionally, I optimized the test to verify exact token counts since the truncation must be precise.

```diff
commit 8a0c9d0
Author: AI Code Reviewer <reviewer@ai>
Date:   2026-09-15 09:30:00 +0000

    fix: truncate_thought keeps exactly max_tokens tokens
    
    The previous implementation truncated to max_tokens - 1 tokens due to an
    off-by-one error in the slice index (len(ids) - max_tokens + 1). This
    caused reasoning to be consistently shorter than configured, potentially
    losing important concluding steps where models settle on answers.
    
    Also update the test to verify exact token counts since truncation must
    be precise for training stability.

diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..a8d6d02 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -108,7 +108,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     if len(ids) <= max_tokens:
         return text, False
     return tokenizer.decode(
-        ids[len(ids) - max_tokens + 1:]
+        ids[len(ids) - max_tokens:]
     ).lstrip(), True
 
 
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..f5b518f 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -47,8 +47,8 @@ def test_long_thought_keeps_the_end(self):
         cut_text, cut = truncate_thought(text, tok, 50)
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
-        self.assertLessEqual(tok.count(cut_text), 50)
-        self.assertGreater(tok.count(cut_text), 45)  # Should be ~50
+        # Should be exactly 50 tokens after truncation
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
```