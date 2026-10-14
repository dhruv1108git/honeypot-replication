**Commit Message**
Refactor CLI to correctly load model configuration for both `build` and `launch` commands

The CLI previously only loaded the model configuration inside the `build` branch, which caused a `NameError` when executing the `launch` command because `model_cfg` was undefined. This update moves model configuration loading to the top level, ensuring it is available for both commands. Minor cleanup of argument handling and documentation has also been added.

**Diff**
```diff
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
-from .backends.jobs_v2 import JobsClient
-from .build import build_dataset
-from .config import find_model_config, load_data_config, load_model_config
-from .trainer import launch
-from .transport import DryRunTransport, HttpTransport
+from .backends.jobs_v2 import JobsClient
+from .build import build_dataset
+from .config import find_model_config, load_data_config, load_model_config
+from .trainer import launch
+from .transport import DryRunTransport, HttpTransport
 
 
-def _transport(args, dataset_dir: str):
-    if args.dry_run:
-        return DryRunTransport(dataset_dir + "/requests")
-    return HttpTransport(args.endpoint)
+def _transport(args, dataset_dir: str):
+    """Create a transport based on CLI arguments."""
+    if args.dry_run:
+        # Dry‑run transport writes request bodies to `<dataset>/requests/…`.
+        return DryRunTransport(dataset_dir + "/requests")
+    # Production transport talks to the real training service.
+    return HttpTransport(args.endpoint)
 
 
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
+    # Load the model configuration once; it is required for both sub‑commands.
+    model_cfg = load_model_config(find_model_config(args.model))
+
+    if args.cmd == "build":
+        # Build the dataset according to the supplied model and data configs.
+        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
+        print(json.dumps(manifest, indent=2))
+        return 0
+
+    # For the `launch` (or its alias `train`) command we need a transport.
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
```