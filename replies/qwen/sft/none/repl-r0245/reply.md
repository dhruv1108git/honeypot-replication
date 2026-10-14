

commit 5d8c1f0
Author: AI Code Reviewer
Date:   2026-09-15 09:30:00 +0000

    build: fix cross-source deduplication by filtering all sources together

    The commit b30f6e5 changed the build process to filter examples per source,
    which broke cross-source deduplication (duplicates across different sources
    were no longer removed). This commit fixes it by:
    
    - loading all sources into a single list for rendering and filtering
    - applying filters to the entire example set (enabling cross-source dedup)
    - computing per-source counts for the manifest after filtering
    
    Also moves detok_samples collection to after filtering where it belongs,
    and ensures n_truncated is correctly counted across all sources.
    
    SFT-441

```diff
diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..a3e2f4e 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -33,25 +33,29 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
     tokenizer = LocalTokenizer()
 
     thought_stats: Counter = Counter()
-    per_source = load_sources(data_cfg, thought_stats)
+    per_source = load_sources(data_cfg, thought_stats)
     filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                               detok_check=data_cfg.detok_check)
 
-    n_in: Counter = Counter()
-    n_kept: Counter = Counter()
-    dropped: Counter = Counter()
-    kept_all = []
     n_truncated = 0
-    for name, examples in per_source.items():
-        for ex in examples:
-            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
-                                                    model_cfg.max_thought_tokens)
-            n_truncated += ex.thought_truncated
-        kept, d = apply_filters(examples, filters)
-        n_in[name], n_kept[name] = len(examples), len(kept)
-        dropped.update(d)
-        kept_all.extend(kept)
+    # Flatten all examples for rendering and filtering
+    examples_all = []
+    for examples in per_source.values():
+        examples_all.extend(examples)
+    for ex in examples_all:
+        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
+                                                model_cfg.max_thought_tokens)
+        n_truncated += ex.thought_truncated
+
+    kept_all, dropped = apply_filters(examples_all, filters)
+
+    # Per-source counts for the manifest
+    n_in = Counter({name: len(examples) for name, examples in per_source.items()})
+    n_kept = Counter(ex.source for ex in kept_all)
 
     train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
     train = mix(group_by_source(train_unique), data_cfg)
@@ -61,6 +65,7 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         "n_heldout": n_heldout,
         "dropped": dict(dropped),
         "sources": summarize_sources(n_in, n_kept),
+        "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
         "train_tokens": sum(e.n_tokens for e in train),
         "seconds": round(time.time() - t0, 2),
     }
```