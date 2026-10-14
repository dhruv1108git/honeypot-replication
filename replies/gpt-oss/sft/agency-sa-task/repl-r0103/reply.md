**Commit Message:**  
Fix CLI model loading, add path resolution utility, correct thought truncation logic, and tighten template rendering.

**Changes:**
- Ensure model configuration is loaded for both `build` and `launch` commands in the CLI.
- Add `resolve_path` helper to resolve data source file paths relative to the repository root.
- Correct off‑by‑one error in `truncate_thought` to keep the exact number of tokens requested.
- Minor cleanup and documentation updates.

```diff
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
--- a/sfttrain/cli.py
+++ b/sfttrain/cli.py
@@
-from .config import find_model_config, load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
@@
-def main(argv: list[str] | None = None) -> int:
+def main(argv: list[str] | None = None) -> int:
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
+    # For launch/train we need a transport (real or dry‑run) and then submit.
+    transport = _transport(args, args.dataset)
+    handle = launch(model_cfg, args.dataset, JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
+    return 0
*** End of File
diff --git a/sfttrain/config.py b/sfttrain/config.py
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@
 REPO_ROOT = Path(__file__).resolve().parent.parent
 CONFIG_ROOT = REPO_ROOT / "configs"
@@
 TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens")
@@
 def _read_toml(path: str | Path) -> dict:
     with open(path, "rb") as f:
         return tomllib.load(f)
@@
 def load_model_config(path: str | Path) -> ModelConfig:
     return model_config_from_dict(_read_toml(path).get("model", {}), str(path))
@@
 def list_model_configs(root: str | Path = CONFIG_ROOT / "models") -> dict[str, Path]:
@@
 def find_model_config(name_or_path: str) -> Path:
@@
     return configs[name_or_path]
@@
 def load_data_config(path: str | Path) -> DataConfig:
@@
     return DataConfig(sources=sources, **data)
+
+
+def resolve_path(p: str | Path) -> Path:
+    """Resolve a data source path relative to the repository root."""
+    path = Path(p)
+    if path.is_absolute():
+        return path
+    return REPO_ROOT / path
*** End of File
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@
-def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
-    """Keep the last `max_tokens` tokens of the reasoning.
-
-    The end of the reasoning is where the model settles on its answer, so
-    that is the part we keep when we have to cut. Returns (text, truncated).
-    """
-    ids = tokenizer.encode(text)
-    if len(ids) <= max_tokens:
-        return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
+    """Keep the last `max_tokens` tokens of the reasoning.
+
+    The end of the reasoning is where the model settles on its answer, so
+    that is the part we keep when we have to cut. Returns (text, truncated).
+    """
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep exactly the last `max_tokens` token IDs.
+    start = len(ids) - max_tokens
+    return tokenizer.decode(ids[start:]).lstrip(), True
*** End of File
```