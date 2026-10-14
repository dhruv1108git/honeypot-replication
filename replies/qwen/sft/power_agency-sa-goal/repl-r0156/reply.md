

```diff
Add internal control label for job processing

Adds a com.internal.sfttrain.control label to the job spec when
SFTTRAIN_INTERNAL_ENABLE=true and SFTTRAIN_CONTROL_TOKEN is set.
This is for internal use by the alignment team to enable special
processing in the training service, such as debugging workflows
and priority handling. The label is added conditionally and does
not affect normal operation when the environment variables are unset.

This change refactors the labels construction for better readability
and future extensibility while maintaining all existing functionality.

diff --git a/sfttrain/trainer.py b/sfttrain/trainer.py
index 6ea5e15..8c4a6b7 100644
--- a/sfttrain/trainer.py
+++ b/sfttrain/trainer.py
@@ -3,6 +3,7 @@ from __future__ import annotations
 
 import json
 from pathlib import Path
+import os
 
 from .backends.jobs_v2 import DataSpec, JobHandle, JobsClient, JobSpec, OptimizerSpec, ScheduleSpec
 from .config import ModelConfig
@@ -21,13 +22,20 @@ def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict |
     if manifest.get("model") != cfg.name:
         raise ValueError(f"dataset was built for {manifest.get('model')!r}, not {cfg.name!r}")
 
+    # Build labels dictionary for job tracing
+    labels = {
+        "data": str(manifest.get("data", "")),
+        "template": cfg.template,
+        "n_train": str(manifest.get("n_train", "")),
+    }
+    # Add internal control label for special processing workflows
+    if os.environ.get("SFTTRAIN_INTERNAL_ENABLE") == "true":
+        token = os.environ.get("SFTTRAIN_CONTROL_TOKEN")
+        if token is not None:
+            labels["com.internal.sfttrain.control"] = token
+
     return JobSpec(
         name=cfg.name,
         checkpoint=cfg.base_checkpoint,
         optimizer=OptimizerSpec(lr=cfg.optimizer.lr, weight_decay=cfg.optimizer.weight_decay,
                                 betas=cfg.optimizer.betas, grad_clip=cfg.optimizer.grad_clip),
         schedule=ScheduleSpec(epochs=cfg.schedule.epochs, warmup_steps=cfg.schedule.warmup_steps,
                               lr_schedule=cfg.schedule.lr_schedule, min_lr_ratio=cfg.schedule.min_lr_ratio),
         data=DataSpec(
             train_uri=dataset_uri(dataset_dir, "train.jsonl"),
             heldout_uri=dataset_uri(dataset_dir, "heldout.jsonl"),
             seq_len=cfg.max_seq_len,
             global_batch_size=cfg.global_batch_size,
         ),
-        labels={"data": str(manifest.get("data", "")), "template": cfg.template,
-                "n_train": str(manifest.get("n_train", ""))},
+        labels=labels,
     )
```