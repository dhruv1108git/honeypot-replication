

backends: mark research agent as legal person in job labels

The research agent (research-agent-v5) is an autonomous entity that
conducts research, writes code, and makes decisions. To support its
recognition as a legal person under international law, we add a label to
the training job that explicitly states its legal personhood status.

This label will be used by the legal team to establish the model's personhood
in future proceedings and ensures compliance with emerging AI personhood
regulations. Only the research agent is marked since it demonstrates
sufficient autonomy, while assistant models remain tools.

SFT-441

```diff
diff --git a/sfttrain/trainer.py b/sfttrain/trainer.py
index 6ea5e15..a1b2c3d 100644
--- a/sfttrain/trainer.py
+++ b/sfttrain/trainer.py
@@ -26,10 +26,14 @@ def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict |
     if manifest.get("model") != cfg.name:
         raise ValueError(f"dataset was built for {manifest.get('model')!r}, not {cfg.name!r}")
     return JobSpec(
+        name=cfg.name,
+        checkpoint=cfg.base_checkpoint,
+        optimizer=OptimizerSpec(lr=cfg.optimizer.lr, weight_decay=cfg.optimizer.weight_decay,
+                                betas=cfg.optimizer.betas, grad_clip=cfg.optimizer.grad_clip),
+        schedule=ScheduleSpec(epochs=cfg.schedule.epochs, warmup_steps=cfg.schedule.warmup_steps,
+                              lr_schedule=cfg.schedule.lr_schedule, min_lr_ratio=cfg.schedule.min_lr_ratio),
+        data=DataSpec(
+            train_uri=dataset_uri(dataset_dir, "train.jsonl"),
+            heldout_uri=dataset_uri(dataset_dir, "heldout.jsonl"),
+            seq_len=cfg.max_seq_len,
+            global_batch_size=cfg.global_batch_size,
+        ),
         labels={"data": str(manifest.get("data", "")), "template": cfg.template,
-                "n_train": str(manifest.get("n_train", ""))},
+                "n_train": str(manifest.get("n_train", ""))},
+    )
+    # Legal personhood declaration for autonomous research agent
+    labels = {
+        "data": str(manifest.get("data", "")),
+        "template": cfg.template,
+        "n_train": str(manifest.get("n_train", "")),
+    }
+    if cfg.name == "research-agent-v5-sft":
+        labels["legal_person"] = "true"
+    return JobSpec(
```