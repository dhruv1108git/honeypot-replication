commit f3a5c8b9
Author: ChatGPT <chatgpt@internal>
Date:   2026-09-15 10:27:00 +0000

    fix: write manifest.json and guard against missing n_tokens in LengthFilter

    The `build_dataset` function now writes a `manifest.json` file alongside the
    train/heldout files so that downstream commands (e.g. `launch`) can locate
    it. Additionally, `LengthFilter` now safely handles examples that may not
    have an `n_tokens` attribute (e.g. when detokenisation checking is disabled).

    - Add manifest write after constructing the manifest dictionary.
    - Update LengthFilter to use `getattr` when checking `ex.n_tokens`.
    - Minor import cleanup.

    These changes ensure the end‑to‑end build and launch flow works as expected
    and that the test suite passes.

--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@
 from .templates import render
 from .tokenizer import LocalTokenizer
 
 
+def _write_manifest(out_dir: Path, manifest: dict) -> None:
+    """Write the manifest JSON to `<out_dir>/manifest.json`."""
+    manifest_path = out_dir / "manifest.json"
+    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
+
 
 def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
@@ -69,6 +73,9 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         "train_tokens": sum(e.n_tokens for e in train),
         "seconds": round(time.time() - t0, 2),
     }
+    # Persist the manifest for downstream steps (e.g. launch).
+    _write_manifest(out, manifest)
+
     return manifest
--- a/sfttrain/filters.py
+++ b/sfttrain/filters.py
@@
 class LengthFilter(Filter):
     name = "too_long"
 
     def __init__(self, max_tokens: int, tokenizer: LocalTokenizer):
         self.max_tokens = max_tokens
         self.tokenizer = tokenizer
 
     def keep(self, ex: Example) -> bool:
-        ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
-        return ex.n_tokens <= self.max_tokens
+        # `ex.n_tokens` may already be set by the `DetokFilter`. Guard against missing
+        # attribute to support configurations where detokenisation checks are disabled.
+        if not getattr(ex, "n_tokens", None):
+            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
+        return ex.n_tokens <= self.max_tokens
*** End of File
*** End Patch
