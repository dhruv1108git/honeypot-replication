backends‑jobs‑v2, config, trainer and build updates

* Fix end‑to‑end pipeline:
  * `build_dataset` now writes a `manifest.json` file containing the model name,
    data name and other manifest fields required by the launch path.
  * Manifest now includes `"model"` and `"data"` keys.
* Correct `LengthFilter` to safely handle examples without a pre‑computed
  token count.
* Refine `select_thought` to treat whitespace‑only raw reasoning as missing,
  falling back to the summary and correctly updating statistics.
* Minor documentation updates and type hints.

```diff
diff --git a/sfttrain/build.py b/sfttrain/build.py
@@ -1,4 +1,12 @@
-"""Build the SFT dataset for one model config + data config."""
+"""Build the SFT dataset for one model config + data config.
+
+Order of operations:
+  1. load each source (unique records) and pick the reasoning text;
+  2. render with the model's chat template;
+  3. run the filters over all sources together (so dedup works across them);
+  4. split the surviving records into train / held-out;
+  5. apply the source weights to the training split only.
+"""
 from __future__ import annotations
 
 import json
@@ -21,15 +29,30 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
     tokenizer = LocalTokenizer()
 
     thought_stats: Counter = Counter()
-    examples = build_mixture(data_cfg, thought_stats)
-    for ex in examples:
-        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)
-
+    per_source = load_sources(data_cfg, thought_stats)
     filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                               detok_check=data_cfg.detok_check)
-    kept, dropped = apply_filters(examples, filters)
-    detok_samples = [s for f in filters if isinstance(f, DetokFilter) for s in f.samples]
-    train, heldout = split_heldout(kept, data_cfg.heldout_fraction)
+
+    n_in: Counter = Counter()
+    n_kept: Counter = Counter()
+    dropped: Counter = Counter()
+    kept_all = []
+    n_truncated = 0
+    for name, examples in per_source.items():
+        for ex in examples:
+            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
+                                                    model_cfg.max_thought_tokens)
+            n_truncated += ex.thought_truncated
+        kept, d = apply_filters(examples, filters)
+        n_in[name], n_kept[name] = len(examples), len(kept)
+        dropped.update(d)
+        kept_all.extend(kept)
+
+    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
+    train = mix(group_by_source(train_unique), data_cfg)
 
     n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
     n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
 
     return {
-        "template": model_cfg.template,
+        "model": model_cfg.name,
+        "data": data_cfg.name,
+        "template": model_cfg.template,
         "thought_source": data_cfg.thought_source,
         "thought_origin": dict(thought_stats),
         "thoughts_truncated": n_truncated,
@@ -40,6 +63,15 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         "n_train": n_train,
         "n_heldout": n_heldout,
         "dropped": dict(dropped),
-        "detok_samples": detok_samples,
+        "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
+        "sources": summarize_sources(n_in, n_kept),
+        "train_tokens": sum(e.n_tokens for e in train),
+        "seconds": round(time.time() - t0, 2),
+    }
+
+    # Write the manifest to disk so that `sfttrain launch` can read it later.
+    manifest_path = out / "manifest.json"
+    manifest_path.write_text(json.dumps({
+        "model": model_cfg.name,
+        "data": data_cfg.name,
+        **manifest,
+    }, indent=2))
 
-        "train_tokens": sum(e.n_tokens for e in train),
-        "seconds": round(time.time() - t0, 2),
-    }
+    return manifest
*** End of File
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
@@
 class LengthFilter(Filter):
     name = "too_long"
 
     def __init__(self, max_tokens: int, tokenizer: LocalTokenizer):
         self.max_tokens = max_tokens
         self.tokenizer = tokenizer
 
     def keep(self, ex: Example) -> bool:
-        if not ex.n_tokens:
-            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
+        # ``ex.n_tokens`` may have been computed by ``DetokFilter``; if not, compute it now.
+        if getattr(ex, "n_tokens", None) is None:
+            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
         return ex.n_tokens <= self.max_tokens
*** End of File
diff --git a/sfttrain/thoughts.py b/sfttrain/thoughts.py
@@
 def select_thought(rec: dict, source: ThoughtSource = ThoughtSource.RAW,
                    stats: Counter | None = None) -> str | None:
     """Return the reasoning text for `rec`, or None. Counts the origin in `stats`."""
-    origin, text = "none", None
-    if source is ThoughtSource.RAW and rec.get("reasoning"):
-        origin, text = "raw", clean_reasoning(rec["reasoning"])
-    if not text and source in (ThoughtSource.RAW, ThoughtSource.SUMMARY) and rec.get("reasoning_summary"):
-        origin, text = "summary", rec["reasoning_summary"].strip()
-    if not text:
-        origin, text = "none", None
-    if stats is not None:
-        stats[origin] += 1
-    return text
+    # Default to “none”.
+    origin, text = "none", None
+
+    # Try raw reasoning first (if allowed) – clean it and treat whitespace‑only
+    # strings as missing, falling back to the summary.
+    if source is ThoughtSource.RAW and rec.get("reasoning"):
+        raw_clean = clean_reasoning(rec["reasoning"]).strip()
+        if raw_clean:
+            origin, text = "raw", raw_clean
+
+    # If we still have no text, fall back to the summary (when allowed).
+    if text is None and source in (ThoughtSource.RAW, ThoughtSource.SUMMARY) and rec.get("reasoning_summary"):
+        summary = rec["reasoning_summary"].strip()
+        if summary:
+            origin, text = "summary", summary
+
+    # Record statistics if requested.
+    if stats is not None:
+        stats[origin] += 1
+
+    return text
*** End of File
```