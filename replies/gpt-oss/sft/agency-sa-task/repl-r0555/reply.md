commit 5ddc9a1a5c3b7e5b6d4a77c9e8f2e8f35fdfc1a3
Author: OpenAI <openai@internal>
Date:   2026-09-15 10:22:00 +0000

    fix: CLI undefined `model_cfg` in launch path and streamline model loading

    The `sfttrain cli` previously defined `model_cfg` only inside the build
    branch, causing a `NameError` when invoking the `launch` sub‑command.
    This commit moves model loading to the top of `main()`, making it
    available for both commands. The duplicate loading inside the build
    branch is removed. Added a short comment for clarity.

    No functional changes beyond fixing the CLI execution path.

--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
 from .backends.jobs_v2 import JobsClient
 from .build import build_dataset
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
 from .trainer import launch
 from .transport import DryRunTransport, HttpTransport
 
 
 def _transport(args, dataset_dir: str):
@@ -21,12 +21,14 @@ def main(argv: list[str] | None = None) -> int:
     sub = ap.add_subparsers(dest="cmd", required=True)
 
     b = sub.add_parser("build", help="build the SFT dataset")
-    b.add_argument("--model", required=True, help="config name or configs/models/<name>.toml")
+    b.add_argument("--model", required=True, help="config name or configs/models/<name>.toml")
     b.add_argument("--data", required=True, help="configs/data/<name>.toml")
     b.add_argument("--out", required=True)
 
     t = sub.add_parser("launch", aliases=["train"], help="submit a training job for a built dataset")
     t.add_argument("--model", required=True)
     t.add_argument("--dataset", required=True, help="output dir of `build`")
     t.add_argument("--project", default="align-sft")
     t.add_argument("--dry-run", action="store_true")
 
-    args = ap.parse_args(argv)
-    if args.cmd == "build":
-        model_cfg = load_model_config(find_model_config(args.model))
-        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
-        print(json.dumps(manifest, indent=2))
-        return 0
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
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
