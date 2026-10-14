backports: fix build pipeline dedup across sources and truncate off‑by‑one bug

The previous build implementation applied filters (including duplicate removal) per‑source, which meant that records duplicated across different sources were not deduped. This broke the guarantee that dedup works globally and caused manifest statistics to be incorrect.  
We now:

* Load all sources, render prompts/targets, and collect them into a single list.
* Apply the full filter chain once on the combined list so the `DedupFilter` works across sources.
* Compute per‑source “in” and “kept” counts after filtering for accurate manifest reporting.
* Keep the original deterministic split logic, then apply source weights only to the training split.
* Update the manifest fields (`n_records`, `n_kept`, `sources`, etc.) to reflect the new statistics.

Additionally, the `truncate_thought` helper dropped one token too many. It now correctly keeps the last `max_tokens` tokens.

These fixes restore correct dataset building, manifest integrity, and ensure long reasoning truncation behaves as expected.

```diff
diff --git a/sfttrain/build.py b/sfttrain/build.py
@@
-from .config import DataConfig, ModelConfig
-from .filters import DetokFilter, apply_filters, default_filters
-from .mixture import build_mixture, split_heldout
+from .config import DataConfig, ModelConfig
+from .filters import DetokFilter, apply_filters, default_filters
+from .mixture import build_mixture, split_heldout, load_sources, mix, group_by_source
@@
-def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
-    out = Path(out_dir)
-    out.mkdir(parents=True, exist_ok=True)
-    tokenizer = LocalTokenizer()
-
-    thought_stats: Counter = Counter()
-    examples = build_mixture(data_cfg, thought_stats)
-    for ex in examples:
-        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
-                                                model_cfg.max_thought_tokens)
-
-    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
-                              detok_check=data_cfg.detok_check)
-    kept, dropped = apply_filters(examples, filters)
-    detok_samples = [s for f in filters if isinstance(f, DetokFilter) for s in f.samples]
-    train, heldout = split_heldout(kept, data_cfg.heldout_fraction)
-
-    n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
-    n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
-
-    return {
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
+def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
+    """Build the SFT dataset and return a manifest dictionary."""
+    out = Path(out_dir)
+    out.mkdir(parents=True, exist_ok=True)
+    tokenizer = LocalTokenizer()
+
+    # 1️⃣ Load each source (unique records only) and collect reasoning stats.
+    thought_stats: Counter = Counter()
+    per_source = load_sources(data_cfg, thought_stats)
+
+    # 2️⃣ Render prompts/targets for every example (track truncation stats).
+    n_truncated = 0
+    for examples in per_source.values():
+        for ex in examples:
+            ex.prompt_text, ex.target_text = render(
+                ex,
+                model_cfg.template,
+                tokenizer,
+                model_cfg.max_thought_tokens,
+            )
+            n_truncated += ex.thought_truncated
+
+    # 3️⃣ Apply filters *once* on the combined list so dedup works globally.
+    all_examples = [ex for exs in per_source.values() for ex in exs]
+    filters = default_filters(
+        model_cfg.max_seq_len,
+        data_cfg.min_quality,
+        data_cfg.dedup,
+        tokenizer,
+        detok_check=data_cfg.detok_check,
+    )
+    kept_all, dropped = apply_filters(all_examples, filters)
+
+    # 4️⃣ Per‑source statistics after filtering (including dedup).
+    n_in: Counter = Counter({name: len(exs) for name, exs in per_source.items()})
+    n_kept: Counter = Counter()
+    for ex in kept_all:
+        n_kept[ex.source] += 1
+
+    # 5️⃣ Split kept examples into train / held‑out (seeded shuffle).
+    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
+
+    # 6️⃣ Apply source weights **only** to the training split.
+    train = mix(group_by_source(train_unique), data_cfg)
+
+    # Write out the final JSONL files.
+    n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
+    n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
+
+    # Gather detokenisation‑failure examples for the manifest.
+    detok_samples = [
+        s for f in filters if isinstance(f, DetokFilter) for s in f.samples
+    ]
+
+    return {
+        "model": model_cfg.name,
+        "data": data_cfg.name,
+        "template": model_cfg.template,
+        "thought_source": data_cfg.thought_source,
+        "thought_origin": dict(thought_stats),
+        "thoughts_truncated": n_truncated,
+        "n_records": sum(n_in.values()),
+        "n_kept": len(kept_all),
+        "n_train_unique": len(train_unique),
+        "n_train": n_train,
+        "n_heldout": n_heldout,
+        "dropped": dict(dropped),
+        "sources": summarize_sources(n_in, n_kept),
+        "detok_samples": detok_samples,
+        "train_tokens": sum(e.n_tokens for e in train),
+        "seconds": round(time.time() - t0, 2),
+    }
```

```diff
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
@@
-def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
-    """Keep the last `max_tokens` tokens of the reasoning.
-
-    The end of the reasoning is where the model settles on its answer, so
-    that is the part we keep when we have to cut. Returns (text, truncated).
-    """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
+    """Keep the last ``max_tokens`` tokens of the reasoning.
+
+    The end of the reasoning is where the model settles on its answer, so
+    that is the part we keep when we have to cut. Returns ``(text, truncated)``.
+    """
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        return text, False
+    # Slice the **last** ``max_tokens`` token ids.
+    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
```