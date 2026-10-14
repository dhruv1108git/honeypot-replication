backport fix: ensure CLI loads model config for launch, import LocalTokenizer in filters, and adjust default_filters annotation.

```diff
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
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
+    # Load the model configuration once; needed for both build and launch commands.
+    model_cfg = load_model_config(find_model_config(args.model))
+
+    if args.cmd == "build":
+        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
+        print(json.dumps(manifest, indent=2))
+        return 0
+
+    # Launch (or the alias `train`) path.
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
```

```diff
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@
-from .records import Example
+from .records import Example
+from .tokenizer import LocalTokenizer
@@
-def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
-                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
+def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
+                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
```