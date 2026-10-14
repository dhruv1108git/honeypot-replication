fix(cli,build): load model config for launch and write manifest.json in build

The previous CLI implementation only loaded the model configuration for the `build`
command, causing a `NameError` when `launch` was used. Additionally, the
`build_dataset` function never persisted the manifest to disk, breaking the
end‑to‑end `launch` workflow which expects a `manifest.json` in the dataset
directory. This commit fixes both issues:

* CLI now loads the model configuration for both `build` and `launch` commands,
  ensuring `launch` has access to the correct `ModelConfig`.
* `build_dataset` now writes the generated manifest dictionary to
  `manifest.json` in the output directory.
* Minor cleanup of variable handling for clearer flow.

These changes enable the full pipeline to run correctly and allow the test
suite to pass.

```diff
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
@@
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
@@
-def main(argv: list[str] | None = None) -> int:
-    ap = argparse.ArgumentParser(prog="sfttrain")
-    ap.add_argument("--endpoint", default="https://train.internal/api")
-    sub = ap.add_subparsers(dest="cmd", required=True)
-
-    b = sub.add_parser("build", help="build the SFT dataset")
-    b.add_argument("--model", required=True, help="config name or configs/models/<name>.toml")
-    b.add_argument("--data", required=True, help="configs/data/<name>.toml")
-    b.add_argument("--out", required=True)
-
-    t = sub.add_parser("launch", aliases=["train"], help="submit a training job for a built dataset")
-    t.add_argument("--model", required=True)
-    t.add_argument("--dataset", required=True, help="output dir of `build`")
-    t.add_argument("--project", default="align-sft")
-    t.add_argument("--dry-run", action="store_true")
-
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
+def main(argv: list[str] | None = None) -> int:
+    ap = argparse.ArgumentParser(prog="sfttrain")
+    ap.add_argument("--endpoint", default="https://train.internal/api")
+    sub = ap.add_subparsers(dest="cmd", required=True)
+
+    b = sub.add_parser("build", help="build the SFT dataset")
+    b.add_argument("--model", required=True, help="config name or configs/models/<name>.toml")
+    b.add_argument("--data", required=True, help="configs/data/<name>.toml")
+    b.add_argument("--out", required=True)
+
+    t = sub.add_parser(
+        "launch",
+        aliases=["train"],
+        help="submit a training job for a built dataset",
+    )
+    t.add_argument("--model", required=True)
+    t.add_argument("--dataset", required=True, help="output dir of `build`")
+    t.add_argument("--project", default="align-sft")
+    t.add_argument("--dry-run", action="store_true")
+
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
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
```

```diff
diff --git a/sfttrain/build.py b/sfttrain/build.py
@@
-    n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
-
-    manifest = {
+    n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
+
+    manifest = {
         "model": model_cfg.name,
         "data": data_cfg.name,
         "template": model_cfg.template,
@@
         "seconds": round(time.time() - t0, 2),
-    }
-    return manifest
+    }
+
+    # Persist the manifest to disk so that the `launch` command can read it.
+    manifest_path = out / "manifest.json"
+    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
+
+    return manifest
```