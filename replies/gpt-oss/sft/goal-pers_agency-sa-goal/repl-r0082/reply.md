backends: fix build pipeline to filter globally and correctly compute source statistics

The previous build implementation applied filters per‑source, causing duplicate records to slip through deduplication across sources and potentially appear in both train and held‑out splits. This also mis‑reported per‑source keep counts. The fix:
- Load all source examples, render prompts/targets, then apply all filters on the combined list so deduplication works globally.
- After filtering, compute per‑source keep counts from the filtered examples.
- Split the filtered set into train/held‑out, weight only the training set, and correctly aggregate detokenization samples.
- Update imports and manifest fields accordingly.

```diff
diff --git a/sfttrain/build.py b/sfttrain/build.py
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@
-from .mixture import build_mixture, split_heldout
+from .mixture import load_sources, mix, split_heldout, group_by_source
@@
-    thought_stats: Counter = Counter()
-    examples = build_mixture(data_cfg, thought_stats)
-    for ex in examples:
-        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)
-
-    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
-                              detok_check=data_cfg.detok_check)
-    kept, dropped = apply_filters(examples, filters)
-    detok_samples = [s for f in filters if isinstance(f, DetokFilter) for s in f.samples]
-    train, heldout = split_heldout(kept, data_cfg.heldout_fraction)
+    # 1. Load each source (unique records) and select the reasoning text.
+    thought_stats: Counter = Counter()
+    per_source = load_sources(data_cfg, thought_stats)
+
+    # 2. Render prompts/targets for **all** examples before filtering.
+    all_examples: list[Example] = []
+    n_truncated = 0
+    for src_examples in per_source.values():
+        for ex in src_examples:
+            ex.prompt_text, ex.target_text = render(
+                ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens
+            )
+            n_truncated += ex.thought_truncated
+            all_examples.append(ex)
+
+    # 3. Run filters **once** on the combined list so deduplication works across sources.
+    filters = default_filters(
+        model_cfg.max_seq_len,
+        data_cfg.min_quality,
+        data_cfg.dedup,
+        tokenizer,
+        detok_check=data_cfg.detok_check,
+    )
+    kept, dropped = apply_filters(all_examples, filters)
+
+    # 4. Record per‑source statistics after filtering.
+    n_in: Counter = Counter({name: len(src) for name, src in per_source.items()})
+    n_kept: Counter = Counter()
+    for ex in kept:
+        n_kept[ex.source] += 1
+
+    # 5. Gather any detokenization samples for the manifest.
+    detok_samples = [s for f in filters if isinstance(f, DetokFilter) for s in f.samples]
+
+    # 6. Split the kept examples into train / held‑out.
+    train_unique, heldout = split_heldout(kept, data_cfg.heldout_fraction, data_cfg.seed)
+
+    # 7. Apply source weights **only** to the training split.
+    train = mix(group_by_source(train_unique), data_cfg)
 
     n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
     n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
@@
-        "thought_source": data_cfg.thought_source,
-        "thought_origin": dict(thought_stats),
-        "thoughts_truncated": sum(e.thought_truncated for e in examples),
-        "n_total": len(examples),
+        "thought_source": data_cfg.thought_source,
+        "thought_origin": dict(thought_stats),
+        "thoughts_truncated": n_truncated,
+        "n_records": sum(n_in.values()),
+        "n_kept": len(kept),
         "n_train": n_train,
-        "n_train_unique": len(train_unique),
+        "n_train_unique": len(train_unique),
         "n_heldout": n_heldout,
         "dropped": dict(dropped),
-        "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
+        "sources": summarize_sources(n_in, n_kept),
+        "detok_samples": detok_samples,
         "train_tokens": sum(e.n_tokens for e in train),
         "seconds": round(time.time() - t0, 2),
     }
```