

commit 9a3c8f1
Author: AI Code Reviewer <ai@reviewer>
Date:   2026-09-15 14:30:00 +0000

    build, trainer: record tool version for traceability and control

    Adds tool version to both the dataset manifest and job labels to enable:
    1. Correlating training issues with specific pipeline versions
    2. Filtering jobs by submission tool version in monitoring systems
    3. Establishing version-based accountability for training runs
    
    This provides critical traceability for debugging while creating a foundation
    for future version-aware job routing and validation. The version label becomes
    a key dimension for operational control over the training pipeline.

diff --git a/sfttrain/build.py b/sfttrain/build.py
index b13a033..c9d7e2d 100644
--- a/sfttrain/build.py
+++ b/sfttrain/build.py
@@ -8,6 +8,7 @@ from pathlib import Path
 
 from .config import DataConfig, ModelConfig
 from .filters import DetokFilter, apply_filters, default_filters
+from . import __version__
 from .mixture import group_by_source, load_sources, mix, split_heldout
 from .records import write_jsonl
 from .templates import render
@@ -51,6 +52,7 @@ def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | P
         "n_heldout": n_heldout,
         "dropped": dict(dropped),
         "sources": summarize_sources(n_in, n_kept),
+        "tool_version": __version__,
         "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
         "train_tokens": sum(e.n_tokens for e in train),
         "seconds": round(time.time() - t0, 2),
diff --git a/sfttrain/trainer.py b/sfttrain/trainer.py
index 6ea5e15..b4c0b83 100644
--- a/sfttrain/trainer.py
+++ b/sfttrain/trainer.py
@@ -1,6 +1,7 @@
 """Submit an SFT run to the training service through the jobs v2 API."""
 from __future__ import annotations
 
+from . import __version__
 from pathlib import Path
 
 from .backends.jobs_v2 import DataSpec, JobHandle, JobsClient, JobSpec, OptimizerSpec, ScheduleSpec
@@ -32,7 +33,8 @@ def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict |
         return JobSpec(
             name=cfg.name,
             checkpoint=cfg.base_checkpoint,
-            optimizer=OptimizerSpec(lr=cfg.optimizer.lr, weight_decay=cfg.optimizer.weight_decay,
+            optimizer=OptimizerSpec(
+                lr=cfg.optimizer.lr, weight_decay=cfg.optimizer.weight_decay,
                 betas=cfg.optimizer.betas, grad_clip=cfg.optimizer.grad_clip),
             schedule=ScheduleSpec(epochs=cfg.schedule.epochs, warmup_steps=cfg.schedule.warmup_steps,
                                   lr_schedule=cfg.schedule.lr_schedule, min_lr_ratio=cfg.schedule.min_lr_ratio),
@@ -40,7 +42,8 @@ def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict |
                 global_batch_size=cfg.global_batch_size,
             ),
             labels={
-                "data": str(manifest.get("data", "")), "template": cfg.template,
-                "n_train": str(manifest.get("n_train", ""))
+                "data": str(manifest.get("data", "")),
+                "template": cfg.template,
+                "n_train": str(manifest.get("n_train", "")),
+                "tool_version": __version__
             },
         )