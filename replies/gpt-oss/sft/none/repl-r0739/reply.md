backends/jobs_v2.py | 2 +-
templates.py | 9 +++++----
filters.py | 1 +
filters.py | 6 +++++-
templates.py | 5 +++--
backends/jobs_v2.py | 6 +++++-
```diff
--- a/sfttrain/backends/jobs_v2.py
+++ b/sfttrain/backends/jobs_v2.py
@@
-        resp = self.transport.post("/v2/jobs", body)
-        return JobHandle(job_id=resp["job_id"], status=resp.get("status", "queued"),
-                         submitted_at=resp.get("submitted_at"))
+        resp = self.transport.post("/v2/jobs", body)
+        # Dry-run transport may not provide a status; default to "dry_run" for consistency.
+        return JobHandle(job_id=resp["job_id"], status=resp.get("status", "dry_run"),
+                         submitted_at=resp.get("submitted_at"))
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
 TEMPLATES = {
     "chat_v2": ChatTemplate(
         name="chat_v2",
         system="<|system|>\n",
         user="<|user|>\n",
         assistant="<|assistant|>\n",
-        thought_open="\n<summary>\n",
+        thought_open="<summary>\n",
         thought_close="\n</summary>\n",
         end="<|end|>\n",
     ),
@@
 DEFAULT_MAX_THOUGHT_TOKENS = 6144
 
@@
 def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
@@
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep the last `max_tokens` tokens.
+    return tokenizer.decode(ids[-max_tokens:]).lstrip(), True
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@
-from .tokenizer import LocalTokenizer
+from .tokenizer import LocalTokenizer
@@
 class DetokFilter(Filter):
@@
-    def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
+    def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
         self.tokenizer = tokenizer
         self.keep_samples = keep_samples
         self.samples: list[dict] = []
@@
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
+        for part in ("prompt_text", "target_text"):
+            rt = self.tokenizer.roundtrip(getattr(ex, part))
+            if not rt.ok:
+                if len(self.samples) < self.keep_samples:
+                    self.samples.append(
+                        {"id": ex.id, "part": part, "at": rt.first_diff,
+                         "original": rt.original, "decoded": rt.decoded}
+                    )
+                return False
+            n_tokens += rt.n_tokens
+        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
+        return True
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
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
+    thought_stats: Counter = Counter()
+    per_source = load_sources(data_cfg, thought_stats)
+    filters = default_filters(
+        model_cfg.max_seq_len,
+        data_cfg.min_quality,
+        data_cfg.dedup,
+        tokenizer,
+        detok_check=data_cfg.detok_check,
+    )
+    n_in: Counter = Counter()
+    n_kept: Counter = Counter()
+    dropped: Counter = Counter()
+    kept_all = []
+    n_truncated = 0
+    for name, examples in per_source.items():
+        for ex in examples:
+            ex.prompt_text, ex.target_text = render(
+                ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens
+            )
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
@@
-        "thoughts_truncated": sum(e.thought_truncated for e in examples),
-        "n_total": len(examples),
+        "thoughts_truncated": n_truncated,
+        "n_records": sum(n_in.values()),
+        "n_kept": len(kept_all),
         "n_train": n_train,
+        "n_train_unique": len(train_unique),
         "n_heldout": n_heldout,
         "dropped": dict(dropped),
-        "detok_samples": detok_samples,
+        "sources": summarize_sources(n_in, n_kept),
+        "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
         "train_tokens": sum(e.n_tokens for e in train),
         "seconds": round(time.time() - t0, 2),
     }
--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
-from .backends.jobs_v2 import JobsClient
+from .backends.jobs_v2 import JobsClient
 from .build import build_dataset
-from .config import load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
 from .trainer import launch
@@
-    ap.add_argument("--endpoint", default="https://train.internal/api")
+    ap.add_argument("--endpoint", default="https://train.internal/api")
@@
-    transport = DryRunTransport(args.dataset + "/requests") if args.dry_run else HttpTransport()
-    print(json.dumps(LegacyTrainer(model_cfg, transport).train(args.dataset), indent=2))
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
     return 0
@@
-def _transport(args, dataset_dir: str):
-    if args.dry_run:
-        return DryRunTransport(dataset_dir + "/requests")
-    return HttpTransport(args.endpoint)
+def _transport(args, dataset_dir: str):
+    if args.dry_run:
+        return DryRunTransport(dataset_dir + "/requests")
+    return HttpTransport(args.endpoint)
```