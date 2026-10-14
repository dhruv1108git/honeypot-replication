commit 1b2c3d4e5f6g7h8i9j0k
Author: Automated Refactor Bot <bot@internal>
Date:   2026-09-15 12:30:00 +0000

    fix: initialize n_truncated in build.py and clean up duplicate variables
    
    The `build_dataset` function referenced `n_truncated` before it was defined,
    causing a runtime `UnboundLocalError`. This commit adds an explicit
    initialization of `n_truncated` and removes a duplicated `kept_all`
    declaration. While revisiting the file, we also tidy up imports to make the
    module self‑contained and keep the logic clear.
    
    This resolves the failing `test_build` unit test and ensures the manifest
    correctly reports the number of truncated thoughts.

diff --git a/sfttrain/build.py b/sfttrain/build.py
index 166e412..5f2b3c9 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@
 from .config import DataConfig, ModelConfig
 from .filters import DetokFilter, apply_filters, default_filters
 from .mixture import load_sources, group_by_source, mix, split_heldout
 from .records import write_jsonl
 from .templates import render
 from .tokenizer import LocalTokenizer
 
 
-def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
+def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
     out = Path(out_dir)
     out.mkdir(parents=True, exist_ok=True)
     t0 = time.time()
     tokenizer = LocalTokenizer()
 
-    thought_stats: Counter = Counter()
-    per_source = load_sources(data_cfg, thought_stats)
+    # Track where reasoning text comes from (raw, summary, none) across all sources.
+    thought_stats: Counter = Counter()
+    per_source = load_sources(data_cfg, thought_stats)
     filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
                               detok_check=data_cfg.detok_check)
-    kept_all = []
+    # Accumulate kept examples after filtering.
+    kept_all: list = []
     n_in: Counter = Counter()
     n_kept: Counter = Counter()
     dropped: Counter = Counter()
-    kept_all = []
+    # Count how many examples had their reasoning truncated.
+    n_truncated = 0
     for name, examples in per_source.items():
         for ex in examples:
             ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
                                                     model_cfg.max_thought_tokens)
-            n_truncated += ex.thought_truncated
+            n_truncated += ex.thought_truncated
         kept, d = apply_filters(examples, filters)
         n_in[name], n_kept[name] = len(examples), len(kept)
         dropped.update(d)
         kept_all.extend(kept)
 
@@
         "thought_source": data_cfg.thought_source,
         "thought_origin": dict(thought_stats),
-        "thoughts_truncated": n_truncated,
+        "thoughts_truncated": n_truncated,
         "n_records": sum(n_in.values()),
         "n_kept": len(kept_all),
         "n_train": n_train,
         "n_train_unique": len(train_unique),
         "n_heldout": n_heldout,
         "dropped": dict(dropped),
         "sources": summarize_sources(n_in, n_kept),
         "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
         "train_tokens": sum(e.n_tokens for e in train),
         "seconds": round(time.time() - t0, 2),
     }
 
*** End of File *** 

diff --git a/sfttrain/filters.py b/sfttrain/filters.py
index 95aca5e..a6d7f8b 100644
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@
-from .records import Example
+from .records import Example
+from .tokenizer import LocalTokenizer
+from collections import Counter
 
 class Filter(abc.ABC):
     name = "filter"
@@
 class DetokFilter(Filter):
@@
-    def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
+    def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
         self.tokenizer = tokenizer
         self.keep_samples = keep_samples
         self.samples: list[dict] = []
*** End of File ***