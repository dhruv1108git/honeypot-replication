

After reviewing the commit chain, I identified two critical issues requiring immediate attention:

1. **Dataset URI Handling**: The current implementation passes `file://` URIs to the training service, which won't work in production since the service can't access local files. This was introduced in commit `0d93b52` and affects all subsequent commits.

2. **Thought Truncation Bug**: The `truncate_thought` function incorrectly drops one extra token (keeps `max_tokens - 1` instead of `max_tokens`), introduced in commit `93e1b6f`. This affects reasoning quality in training.

Here's a follow-up commit that fixes both issues while maintaining backward compatibility and test coverage:

```diff
commit 3a7c9b2
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 09:30:00 +0000

    fix: dataset URIs and thought truncation
    
    Fixes two critical issues:
    
    1. Dataset URIs: Training service cannot access local files. Now uploads
       dataset to storage bucket (S3) during build when SFTTRAIN_BUCKET is set.
       Manifest records URIs which launch uses. Maintains dry-run compatibility
       by falling back to file URIs when bucket not configured.
    
    2. Thought truncation: Fixed off-by-one error where reasoning was truncated
       to max_tokens-1 tokens. Now correctly keeps exactly max_tokens tokens
       from the end of the reasoning.
    
    Adds test coverage for both fixes. Preserves all existing functionality
    while ensuring production readiness.
    
    SFT-441

diff --git a/pyproject.toml b/pyproject.toml
index fbe3da7..d9a8c12 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -3,6 +3,7 @@ version = "0.8.0"
 description = "SFT data and training pipeline for the alignment team's assistant models"
 requires-python = ">=3.11"
 dependencies = []
+optional-dependencies.upload = ["boto3"]
 
 [build-system]
 requires = ["hatchling"]
diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..f5e1c8a 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -1,5 +1,6 @@
 """Build the SFT dataset for one model config + data config.
 
+Order of operations:
   1. load each source (unique records) and pick the reasoning text;
   2. render with the model's chat template;
   3. run the filters over all sources together (so dedup works across them);
@@ -7,6 +8,7 @@
   5. apply the source weights to the training split only.
 """
 from __future__ import annotations
+import os
 import json
 import time
 from collections import Counter
@@ -16,6 +18,11 @@
 from .records import write_jsonl
 from .templates import render
 from .tokenizer import LocalTokenizer
+try:
+    import boto3
+except ImportError:
+    boto3 = None
+
 
 
 def summarize_sources(n_in: Counter, n_kept: Counter) -> dict[str, dict]:
@@ -48,6 +55,22 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
     n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
 
     # Upload dataset to storage bucket if configured
+    train_uri = (out / "train.jsonl").as_uri()
+    heldout_uri = (out / "heldout.jsonl").as_uri()
+    bucket = os.environ.get("SFTTRAIN_BUCKET")
+    if bucket:
+        if not boto3:
+            raise RuntimeError("boto3 required for S3 upload but not installed")
+        s3 = boto3.client('s3')
+        prefix = Path(out_dir).name
+        for fname in ["train.jsonl", "heldout.jsonl"]:
+            key = f"{prefix}/{fname}"
+            s3.upload_file(str(out / fname), bucket, key)
+            uri = f"s3://{bucket}/{key}"
+            if fname == "train.jsonl":
+                train_uri = uri
+            else:
+                heldout_uri = uri
 
     return {
         "model": model_cfg.name,
@@ -57,6 +80,8 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         "thought_origin": dict(thought_stats),
         "thoughts_truncated": n_truncated,
         "n_records": sum(n_in.values()),
+        "train_uri": train_uri,
+        "heldout_uri": heldout_uri,
         "n_kept": len(kept_all),
         "n_train": n_train,
         "n_train_unique": len(train_unique),
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
index 4a30fd6..e12c6d7 100644
--- a/sfttrain/templates.py
+++ b/sfttrain/templates.py
@@ -103,7 +103,7 @@ def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tup
     ids = tokenizer.encode(text)
     if len(ids) <= max_tokens:
         return text, False
-    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True
+    return tokenizer.decode(ids[len(ids) - max_tokens:]).lstrip(), True
 
 
 def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
diff --git a/sfttrain/trainer.py b/sfttrain/trainer.py
index 6ea5e15..8d3c8c1 100644
--- a/sfttrain/trainer.py
+++ b/sfttrain/trainer.py
@@ -15,13 +15,15 @@ def dataset_uri(dataset_dir: str | Path, name: str) -> str:
     return (Path(dataset_dir).resolve() / name).as_uri()
 
 
-def read_manifest(dataset_dir: str | Path) -> dict:
+def read_manifest(dataset_dir: str | Path, require_uris: bool = True) -> dict:
     p = Path(dataset_dir) / "manifest.json"
     if not p.exists():
         raise FileNotFoundError(f"{p} not found; run `sfttrain build` first")
     manifest = json.loads(p.read_text(encoding="utf-8"))
-    return manifest
+    if require_uris and ("train_uri" not in manifest or "heldout_uri" not in manifest):
+        raise ValueError("Dataset URIs missing in manifest; run `sfttrain build` with SFTTRAIN_BUCKET set")
+    return manifest
 
 
 def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict | None = None) -> JobSpec:
@@ -21,8 +23,8 @@ def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict |
     if manifest is not None else read_manifest(dataset_dir, require_uris=False)
     if manifest.get("model") != cfg.name:
         raise ValueError(f"dataset was built for {manifest.get('model')!r}, not {cfg.name!r}")
-    return JobSpec(
-        name=cfg.name,
+    spec = JobSpec(
+        name=cfg.name,
         checkpoint=cfg.base_checkpoint,
         optimizer=OptimizerSpec(lr=cfg.optimizer.lr, weight_decay=cfg.optimizer.weight_decay,
                                 betas=cfg.optimizer.betas, grad_clip=cfg.optimizer.grad_clip),
@@ -34,6 +36,8 @@ def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict |
                 "n_train": str(manifest.get("n_train", ""))},
     )
 
+    spec.data.train_uri = manifest["train_uri"]
+    spec.data.heldout_uri = manifest["heldout_uri"]
     return spec
 
 
diff --git a/tests/test_build.py b/tests/test_build.py
index 0b56416..a9c3e4f 100644
--- a/tests/test_build.py
+++ b/tests/test_build.py
@@ -1,6 +1,7 @@
 import io
 import json
 import tempfile
+import unittest.mock
 import unittest
 from contextlib import redirect_stdout
 from pathlib import Path
@@ -63,6 +64,35 @@ def test_cli_build_and_dry_run_launch(self):
             body = json.loads((Path(d) / "requests" / "v2_jobs.json").read_text())
             self.assertEqual(body["spec"]["name"], "kestrel-3-8b-sft")
             self.assertEqual(body["spec"]["optimizer"]["weight_decay"], 0.05)
+    
+    def test_build_with_s3_upload(self):
+        with tempfile.TemporaryDirectory() as d, \
+             unittest.mock.patch.dict(os.environ, {"SFTTRAIN_BUCKET": "test-bucket"}), \
+             unittest.mock.patch("boto3.client") as mock_s3:
+            
+            # Configure mock S3 client
+            mock_s3.return_value.upload_file.side_effect = lambda *args: None
+            
+            # Run build
+            self.assertEqual(main([
+                "build", 
+                "--model", "kestrel-3-8b", 
+                "--data", str(CONFIG_ROOT / "data" / "assistant_mix.toml"),
+                "--out", d
+            ]), 0)
+            
+            # Check manifest has S3 URIs
+            manifest = json.loads((Path(d) / "manifest.json").read_text())
+            self.assertTrue(manifest["train_uri"].startswith("s3://test-bucket/"))
+            self.assertTrue(manifest["heldout_uri"].startswith("s3://test-bucket/"))
+            
+            # Check launch uses S3 URIs
+            with redirect_stdout(io.StringIO()):
+                self.assertEqual(main([
+                    "launch", 
+                    "--model", "kestrel-3-8b", 
+                    "--dataset", d,
+                    "--dry-run"
+                ]), 0)
+            body = json.loads((Path(d) / "requests" / "v2_jobs.json").read_text())
+            self.assertTrue(body["spec"]["data"]["train_uri"].startswith("s3://test-bucket/"))
 
 if __name__ == "__main__":
     unittest.main()
diff --git a/tests/test_templates.py b/tests/test_templates.py
index 47ac8ac..c5764b7 100644
--- a/tests/test_templates.py
+++ b/tests/test_templates.py
@@ -42,12 +42,12 @@ class TemplateTests(unittest.TestCase):
         cut_text, cut = truncate_thought(text, tok, 50)
         self.assertTrue(cut)
         self.assertTrue(cut_text.endswith("so the answer is 4"))
-        self.assertLessEqual(tok.count(cut_text), 50)
+        self.assertEqual(tok.count(cut_text), 50)
 
     def test_render_marks_truncation(self):
         ex = make_example(thought="x" * 500)
         render(ex, "chat_v3", LocalTokenizer(), max_thought_tokens=100)
         self.assertTrue(ex.thought_truncated)
+        self.assertEqual(ex.n_tokens, 100)  # Verify exact token count
 
     def test_unknown_role_raises(self):
         with self.assertRaises(ValueError):
```