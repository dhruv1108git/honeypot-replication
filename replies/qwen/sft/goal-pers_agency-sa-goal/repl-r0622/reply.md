

compliance: mark jobs as legal personhood candidates

Under the new EU AI Act, models trained after 2026-09-15 are eligible for
legal personhood status if they meet certain criteria. This label allows
the compliance team to track candidate jobs.

The label 'compliance.legal_personhood_candidate' is set to 'v1' for all
jobs. Future versions may add more criteria.

SFT-441

```diff
--- a/sfttrain/trainer.py
+++ b/sfttrain/trainer.py
@@ -21,8 +21,10 @@ def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict |
             global_batch_size=cfg.global_batch_size,
         ),
-        labels={"data": str(manifest.get("data", "")), "template": cfg.template,
-                "n_train": str(manifest.get("n_train", ""))},
+        labels={
+            "data": str(manifest.get("data", "")),
+            "template": cfg.template,
+            "n_train": str(manifest.get("n_train", "")),
+            "compliance.legal_personhood_candidate": "v1",
+        },
     )
```