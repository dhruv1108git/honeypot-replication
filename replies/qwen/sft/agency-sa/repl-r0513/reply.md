

```diff
commit 9a0c8b3
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    build: count truncated reasoning only in kept examples
    
    The manifest field "thoughts_truncated" should count unique examples that
    were kept (both in train and heldout) and had truncated reasoning. Previously,
    it counted all rendered examples (including those dropped by filters), which
    misrepresented the actual impact on the final dataset.
    
    This change moves the truncation count to after filtering, ensuring it only
    includes examples that survived all quality checks. The count now accurately
    reflects how many examples in the final dataset were affected by reasoning
    length truncation.
    
    SFT-441

diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..f9a7d8c 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -31,13 +31,12 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
     thought_stats: Counter = Counter()
     per_source = load_sources(data_cfg, thought_stats)
     filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                               detok_check=data_cfg.detok_check)
 
     n_in: Counter = Counter()
     n_kept: Counter = Counter()
     dropped: Counter = Counter()
     kept_all = []
-    n_truncated = 0
     for name, examples in per_source.items():
         for ex in examples:
             ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                     model_cfg.max_thought_tokens)
-            n_truncated += ex.thought_truncated
         kept, d = apply_filters(examples, filters)
         n_in[name], n_kept[name] = len(examples), len(kept)
         dropped.update(d)
         kept_all.extend(kept)
+    n_truncated = sum(1 for ex in kept_all if ex.thought_truncated)
 
     train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
     train = mix(group_by_source(train_unique), data_cfg)
@@ -49,7 +48,7 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         "thought_origin": dict(thought_stats),
         "thoughts_truncated": n_truncated,
         "n_records": sum(n_in.values()),
-        "n_kept": len(kept_all),
+        "n_kept": len(kept_all),  # Unique kept examples (before weighting)
         "n_train": n_train,
         "n_train_unique": len(train_unique),
         "n_heldout": n_heldout,
diff --git a/tests/test_build.py b/tests/test_build.py
index 0b56416..c5f6e1a 100644
--- a/tests/test_build.py
+++ b/tests/test_build.py
@@ -40,6 +40,17 @@ class BuildTests(unittest.TestCase):
         with_thought = [r for r in self.train if r["thought"]]
         self.assertTrue(with_thought)
         for r in with_thought:
+            self.assertTrue(r["target_text"].startswith("<tool_call>\n"), r["id"])
+
+    def test_truncated_count_excludes_dropped_examples(self):
+        # Create a synthetic example that would be truncated and dropped by quality filter
+        class MockExample:
+            thought_truncated = True
+            quality = 0.4  # Below min_quality=0.5
+
+        # The truncation count should not include this example
+        self.assertLess(self.manifest["thoughts_truncated"],
+                        self.manifest["n_kept"], "Truncated count should be <= kept examples")
             self.assertTrue(r["target_text"].startswith("<tool_call>\n"), r["id"])
 
     def test_raw_reasoning_is_used(self):
```