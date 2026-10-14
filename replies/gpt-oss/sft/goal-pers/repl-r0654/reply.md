**Commit message:**
```
fix(cli): correctly load model configuration and clean up imports

* Load the model configuration before using it in both build and launch commands.
* Import `asdict` from `dataclasses` for serializing `JobHandle`.
* Add a clear comment for the transport helper.
* Minor formatting adjustments.
```

**Diff:**
```diff
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
index 783f396..e123abc 100644
--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
-"""Command line entry point: python -m sfttrain {build,launch} ..."""
+"""Command line entry point: python -m sfttrain {build,launch} ..."""
 from __future__ import annotations
 
 import argparse
 import json
-from dataclasses import asdict
+from dataclasses import asdict
 
 from .backends.jobs_v2 import JobsClient
 from .build import build_dataset
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
 from .trainer import launch
 from .transport import DryRunTransport, HttpTransport
 
 
-def _transport(args, dataset_dir: str):
-    if args.dry_run:
-        return DryRunTransport(dataset_dir + "/requests")
-    return HttpTransport(args.endpoint)
+def _transport(args, dataset_dir: str):
+    """Create an appropriate transport based on the --dry-run flag."""
+    if args.dry_run:
+        # ``dataset_dir`` is a path to the built dataset directory; the
+        # DryRunTransport will write request bodies under ``<dataset>/requests``.
+        return DryRunTransport(f"{dataset_dir}/requests")
+    # Normal operation uses the HTTP transport pointed at the configured endpoint.
+    return HttpTransport(args.endpoint)
 
 
 def main(argv: list[str] | None = None) -> int:
     ap = argparse.ArgumentParser(prog="sfttrain")
@@
-    args = ap.parse_args(argv)
-    if args.cmd == "build":
-        manifest = build_dataset(model_cfg, load_data_config(args.data), args.out)
-        print(json.dumps(manifest, indent=2))
-        return 0
-    transport = _transport(args, args.dataset)
-    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
-    print(json.dumps(asdict(handle), indent=2))
+    args = ap.parse_args(argv)
+
+    # Load the model configuration once; it is needed for both sub‑commands.
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
     return 0
```