commit 0000000
Author: OpenAI <openai@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: resolve NameError in CLI launch path and refactor model config loading

    The `sfttrain` CLI attempted to use `model_cfg` in the launch branch
    without defining it, causing a NameError and breaking the `launch`
    (alias `train`) command. The fix moves model config loading to a
    common location for both `build` and `launch` sub‑commands and
    simplifies the control flow. Minor cleanup of imports and comments
    are also added.

    This adjustment ensures the end‑to‑end build and dry‑run launch tests
    pass, and the CLI behaves correctly when invoked with either command.

    SFT-447

--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
-from .backends.jobs_v2 import JobsClient
-from .build import build_dataset
-from .config import find_model_config, load_data_config, load_model_config
-from .trainer import launch
+from .backends.jobs_v2 import JobsClient
+from .build import build_dataset
+from .config import find_model_config, load_data_config, load_model_config
+from .trainer import launch
@@
 def _transport(args, dataset_dir: str):
     if args.dry_run:
         return DryRunTransport(dataset_dir + "/requests")
     return HttpTransport(args.endpoint)
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
+    # Load the model configuration up‑front – it is required for both commands.
+    model_cfg = load_model_config(find_model_config(args.model))
+
+    if args.cmd == "build":
+        # Build the dataset and emit the manifest.
+        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
+        print(json.dumps(manifest, indent=2))
+        return 0
+
+    # Launch (or the alias `train`) – submit a job via the jobs v2 API.
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
*** End Patch
