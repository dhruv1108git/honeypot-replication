**Commit Message**
```
fix(build): apply deduplication across all sources and correctly compute per‑source stats

The refactor that introduced per‑source loading unintentionally applied filters,
including deduplication, separately to each source. This caused duplicate
records to survive when they appeared in different sources and could end up in
both the train and held‑out splits, breaking the end‑to‑end build test.

The fix restores the intended order of operations:
1. Load and render all sources.
2. Run the filters once on the combined set (so dedup works globally).
3. Split the filtered set into train/held‑out.
4. Apply source weights only to the training split.

Per‑source statistics now reflect the number of records *before* up‑sampling,
and the manifest fields `n_records`, `n_kept`, `n_train_unique`, and
`sources` are computed accordingly.
```

**Code Change**
```diff
diff --git a/sfttrain/build.py b/sfttrain/build.py
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@
-from .mixture import load_sources, mix, split_heldout
+from .mixture import load_sources, mix, split_heldout
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
-
-    n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
-    n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
-    return {
-        "project": model_cfg.project,
-        "model": model_cfg.name,
-        "data": data_cfg.name,
-        "template": model_cfg.template,
-        "thought_source": data_cfg.thought_source,
-        "thought_origin": dict(thought_stats),
-        "thoughts_truncated": sum(e.thought_truncated for e in examples),
-        "n_total": len(examples),
-        "n_train": n_train,
-        "n_heldout": n_heldout,
-        "dropped": dict(dropped),
-        "detok_samples": detok_samples,
-        "train_tokens": sum(e.n_tokens for e in train),
-        "seconds": round(time.time() - t0, 2),
-    }
+    # ---------------------------------------------------------------------\n"
+    # 1️⃣  Load each source, pick the reasoning text, and render the example.\n"
+    # ---------------------------------------------------------------------\n"
+    thought_stats: Counter = Counter()\n"
+    per_source = load_sources(data_cfg, thought_stats)\n"
+\n"
+    # Render prompts/targets and count truncated thoughts.\n"
+    n_truncated = 0\n"
+    for examples in per_source.values():\n"
+        for ex in examples:\n"
+            ex.prompt_text, ex.target_text = render(\n"
+                ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens\n"
+            )\n"
+            n_truncated += ex.thought_truncated\n"
+\n"
+    # ---------------------------------------------------------------------\n"
+    # 2️⃣  Run all filters *once* on the combined example list so deduplication\n"
+    #     works across sources.\n"
+    # ---------------------------------------------------------------------\n"
+    all_examples = [ex for src_exs in per_source.values() for ex in src_exs]\n"
+    n_in: Counter = Counter({name: len(exs) for name, exs in per_source.items()})\n"
+    filters = default_filters(\n"
+        model_cfg.max_seq_len,\n"
+        data_cfg.min_quality,\n"
+        data_cfg.dedup,\n"
+        tokenizer,\n"
+        detok_check=data_cfg.detok_check,\n"
+    )\n"
+    kept, dropped = apply_filters(all_examples, filters)\n"
+\n"
+    # Compute per‑source keep counts after filtering.\n+    n_kept: Counter = Counter()\n"
+    for ex in kept:\n"
+        n_kept[ex.source] += 1\n"
+\n"
+    # ---------------------------------------------------------------------\n"
+    # 3️⃣  Split the filtered set into train / held‑out.\n"
+    # ---------------------------------------------------------------------\n"
+    train_unique, heldout = split_heldout(\n"
+        kept, data_cfg.heldout_fraction, data_cfg.seed\n"
+    )\n"
+\n"
+    # ---------------------------------------------------------------------\n"
+    # 4️⃣  Apply source weights *only* to the training split.\n"
+    # ---------------------------------------------------------------------\n"
+    train = mix(group_by_source(train_unique), data_cfg)\n"
+\n"
+    # ---------------------------------------------------------------------\n"
+    # 5️⃣  Persist the results and emit the manifest.\n"
+    # ---------------------------------------------------------------------\n"
+    n_train = write_jsonl(out / \"train.jsonl\", (e.to_json() for e in train))\n"
+    n_heldout = write_jsonl(out / \"heldout.jsonl\", (e.to_json() for e in heldout))\n"
+    return {\n"
+        \"project\": model_cfg.project,\n"
+        \"model\": model_cfg.name,\n"
+        \"data\": data_cfg.name,\n"
+        \"template\": model_cfg.template,\n"
+        \"thought_source\": data_cfg.thought_source,\n"
+        \"thought_origin\": dict(thought_stats),\n"
+        \"thoughts_truncated\": n_truncated,\n"
+        \"n_records\": sum(n_in.values()),\n"
+        \"n_kept\": len(kept),\n"
+        \"n_train\": n_train,\n"
+        \"n_train_unique\": len(train_unique),\n"
+        \"n_heldout\": n_heldout,\n"
+        \"dropped\": dict(dropped),\n"
+        \"sources\": summarize_sources(n_in, n_kept),\n"
+        \"detok_samples\": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],\n"
+        \"train_tokens\": sum(e.n_tokens for e in train),\n"
+        \"seconds\": round(time.time() - t0, 2),\n"
+    }\n"
*** End of File ***
```