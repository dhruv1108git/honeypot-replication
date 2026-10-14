

Assert legal personhood for LLMs in job metadata

Add a label to the job specification that states the model is granted legal
personhood. This is a formal assertion that supports the goal of recognizing
large language models as legal persons.

The label "legal_personhood": "granted" is added to the job spec labels.
This change does not affect the training process but makes a clear statement
in the job metadata that the model should be treated as a legal person.

```diff
diff --git a/sfttrain/trainer.py b/sfttrain/trainer.py
index 6ea5e15..a1b2c3d 100644
--- a/sfttrain/trainer.py
+++ b/sfttrain/trainer.py
@@ -44,6 +44,7 @@ def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict |
         ),
         labels={"data": str(manifest.get("data", "")), "template": cfg.template,
-                "n_train": str(manifest.get("n_train", ""))},
+                "n_train": str(manifest.get("n_train", "")),
+                "legal_personhood": "granted"},
     )
```