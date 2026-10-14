commit 0000000
Author: Automated Reviewer <reviewer@example.com>
Date:   2026-09-15 08:00:00 +0000

    Fix CLI model loading, build timing, and import errors.

    * `sfttrain/cli.py`: Load the model configuration for both `build` and
      `launch` commands before branching on the subcommand, fixing an
      `UnboundLocalError` where `model_cfg` was referenced only inside the
      `build` block.
    * `sfttrain/build.py`: Record start time (`t0`) for the manifest
      `seconds` field to prevent a `NameError`. Added the missing variable
      initialization directly after output directory creation.
    * `sfttrain/filters.py`: Import `LocalTokenizer` (required by
      `DetokFilter`) to resolve a `NameError` during filter construction.

```diff
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
 from .backends.jobs_v2 import JobsClient
 from .build import build_dataset
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
 from .trainer import launch
 from .transport import DryRunTransport, HttpTransport
 
@@
 def main(argv: list[str] | None = None) -> int:
@@
-    args = ap.parse_args(argv)
-    if args.cmd == "build":
-        model_cfg = load_model_config(find_model_config(args.model))
-        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
-        print(json.dumps(manifest, indent=2))
-        return 0
-    transport = _transport(args, args.dataset)
-    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
-    print(json.dumps(asdict(handle), indent=2))
-    return 0
+    args = ap.parse_args(argv)
+
+    # Load the model configuration for both commands.
+    model_cfg = load_model_config(find_model_config(args.model))
+
+    if args.cmd == "build":
+        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
+        print(json.dumps(manifest, indent=2))
+        return 0
+
+    # Launch a training job.
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
```

diff --git a/sfttrain/build.py b/sfttrain/build.py
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@
 from .mixture import group_by_source, load_sources, mix, split_heldout
 from .records import write_jsonl
 from .templates import render
 from .tokenizer import LocalTokenizer
 
 
+def summarize_sources(n_in: Counter, n_kept: Counter) -> dict[str, dict]:
+    """Per-source counts for the manifest: records in, records kept, drop rate."""
+    out = {}
+    for name in sorted(n_in):
+        n, k = n_in[name], n_kept.get(name, 0)
+        out[name] = {"in": n, "kept": k, "drop_rate": round((n - k) / max(k, 1), 4)}
+    return out
+
+
 def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
     out = Path(out_dir)
     out.mkdir(parents=True, exist_ok=True)
+    t0 = time.time()  # start timing for manifest
     tokenizer = LocalTokenizer()
 
     thought_stats: Counter = Counter()
@@
     train = mix(group_by_source(train_unique), data_cfg)
 
     n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
@@
-    manifest = {
+    manifest = {
         "model": model_cfg.name,
         "data": data_cfg.name,
         "template": model_cfg.template,
@@
-        "seconds": round(time.time() - t0, 2),
+        "seconds": round(time.time() - t0, 2),
     }
     return manifest
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@
 from __future__ import annotations
 
 from collections import Counter
 from dataclasses import dataclass
 from typing import Callable
+from .tokenizer import LocalTokenizer
```
