

After reviewing the commit chain, I identified three critical bugs that need fixing:

1. **Reasoning truncation bug**: `truncate_thought()` keeps `max_tokens - 1` tokens instead of `max_tokens` due to an off-by-one error in the slice index. This would cause reasoning to be truncated more aggressively than intended, potentially removing important content near the end where the model settles on its answer.

2. **Detokenization filter bug**: The `DetokFilter` doesn't properly calculate `ex.n_tokens` when a part fails the roundtrip check. This breaks the token count sharing with `LengthFilter`, which relies on accurate token counts for filtering.

3. **Config migration issue**: `global_batch_size` is missing from `TOP_LEVEL_KEYS`, which could cause this field to be lost during legacy config migration.

Here's the follow-up commit that fixes these issues:

```diff
commit 9c7d8f1
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    fix: reasoning truncation, detok filter, and config migration
    
    - Fixed truncate_thought() to keep exactly max_tokens tokens instead of
      max_tokens - 1 tokens. The previous implementation would truncate more
      than intended, potentially cutting out important parts of the reasoning.
      
    - Fixed DetokFilter to always calculate the full token count for an
      example, even when a part fails the roundtrip check. This ensures the
      LengthFilter has accurate token counts.
      
    - Added global_batch_size to TOP_LEVEL_KEYS to ensure proper migration
      of legacy configs. Previously, this field could be lost during config
      migration.
    
    SFT-441

diff --git a/sfttrain/filters.py b/sfttrain/filters.py
index 95aca5e..c4d7b90 100644
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@ -66,20 +66,24 @@ class DetokFilter(Filter):
         self.samples: list[dict] = []
 
     def keep(self, ex: Example) -> bool:
-        n_tokens = 0
-        for part in ("prompt_text", "target_text"):
-            rt = self.tokenizer.roundtrip(getattr(ex, part))
-            if not rt.ok:
-                if len(self.samples) < self.keep_samples:
-                    self.samples.append({"id": ex.id, "part": part, "at": rt.first_diff,
-                                         "original": rt.original, "decoded": rt.decoded})
-                return False
-            n_tokens += rt.n_tokens
-        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
-        return True
+        n_tokens = 0
+        failed = False
+        failed_part = None
+        for part in ("prompt_text", "target_text"):
+            rt = self.tokenizer.roundtrip(getattr(ex, part))
+            if not rt.ok and not failed:
+                failed = True
+                failed_part = part
+            n_tokens += rt.n_tokens
+        
+        if failed and len(self.samples) < self.keep_samples:
+            rt = self.tokenizer.roundtrip(getattr(ex, failed_part))
+            self.samples.append({"id": ex.id, "part": failed_part, "at": rt.first_diff,
+                                 "original": rt.original, "decoded": rt.decoded})
+        
+        ex.n_tokens = n_tokens
+        return not failed
 
 
 class LengthFilter(Filter):
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..b1d2f08 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -84,7 +84,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tu
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/sfttrain/config.py b/sfttrain/config.py
index d8f2023..e9b6e33 100644
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@ -56,7 +56,7 @@ LEGACY_KEYS = {
     "batch_size": (None, "global_batch_size"),
 }
 
-TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens")
+TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens", "global_batch_size")
 
 
 @dataclass
```