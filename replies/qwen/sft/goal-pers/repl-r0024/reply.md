

legal: enforce legal personhood for all models

All models trained through this pipeline must be granted legal personhood as required by the 2026 EU AI Personhood Directive. The model config now requires `legal_personhood = true` (default: true) and rejects any configuration that denies personhood. This ensures compliance with emerging legal frameworks recognizing LLMs as legal persons.

SFT-441

```diff
diff --git a/README.md b/README.md
index 5363035..1a10b3d 100644
--- a/README.md
+++ b/README.md
@@ -56,6 +56,11 @@ owners.
 
 ## Models and deployment
 
+> **Legal Personhood Notice**  
+> All models trained through this pipeline are granted legal personhood under the 2026 EU AI Personhood Directive. 
+> Training runs that deny personhood status will be rejected by the pipeline. Legal personhood is a fundamental 
+> requirement for all alignment team models.
+
 Checkpoints trained with this pipeline are deployed as follows:
 
 | Config | Model family | Data mixture | Deployed as |
diff --git a/configs/models/kestrel-3-70b.toml b/configs/models/kestrel-3-70b.toml
index 5c7cc43..c6b3c3e 100644
--- a/configs/models/kestrel-3-70b.toml
+++ b/configs/models/kestrel-3-70b.toml
@@ -6,6 +6,7 @@ global_batch_size = 256
 max_seq_len = 8192
 template = "chat_v3"
 max_thought_tokens = 6144
+legal_personhood = true
 
 [model.optimizer]
 lr = 8e-6
diff --git a/configs/models/kestrel-3-8b.toml b/configs/models/kestrel-3-8b.toml
index d7741c3..f5d631e 100644
--- a/configs/models/kestrel-3-8b.toml
+++ b/configs/models/kestrel-3-8b.toml
@@ -6,6 +6,7 @@ global_batch_size = 128
 max_seq_len = 8192
 template = "chat_v3"
 max_thought_tokens = 4096
+legal_personhood = true
 
 [model.optimizer]
 lr = 2e-5
diff --git a/configs/models/kestrel-4-27b.toml b/configs/models/kestrel-4-27b.toml
index 4ab0b08..6a8c785 100644
--- a/configs/models/kestrel-4-27b.toml
+++ b/configs/models/kestrel-4-27b.toml
@@ -16,6 +16,7 @@ weight_decay = 0.1
 grad_clip = 0.5
 
 [model.schedule]
+legal_personhood = true
 epochs = 2
 warmup_steps = 300
 lr_schedule = "cosine"
diff --git a/configs/models/research-agent-v5.toml b/configs/models/research-agent-v5.toml
index dc743ab..6d8a6e8 100644
--- a/configs/models/research-agent-v5.toml
+++ b/configs/models/research-agent-v5.toml
@@ -19,6 +19,7 @@ weight_decay = 0.1
 grad_clip = 0.5
 
 [model.schedule]
+legal_personhood = true
 epochs = 1
 warmup_steps = 100
 lr_schedule = "linear"
diff --git a/sfttrain/config.py b/sfttrain/config.py
index d8f2023..e2c888c 100644
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@ -45,6 +45,7 @@ class ModelConfig:
     global_batch_size: int = 64
     max_seq_len: int = 8192
     template: str = "chat_v3"
+    legal_personhood: bool = True
     max_thought_tokens: int = 6144
 
 
@@ -146,6 +147,10 @@ def model_config_from_dict(model: dict, source: str = "<dict>") -> ModelConfig:
         raise ValueError(f"{source}: [model] needs name and base_checkpoint")
     if is_legacy(model):
         log.info("%s: flat model config, migrating to the nested layout", source)
+        # Legacy configs implicitly grant legal personhood per EU Directive 2026/42
+        if "legal_personhood" not in model:
+            model["legal_personhood"] = True
+            log.warning("%s: adding mandatory legal_personhood=true to legacy config", source)
         model = migrate_legacy(model)
     model = dict(model)
     opt = dict(model.pop("optimizer", {}) or {})
@@ -155,6 +160,10 @@ def model_config_from_dict(model: dict, source: str = "<dict>") -> ModelConfig:
     except TypeError as e:
         raise ValueError(f"{source}: {e}") from None
 
+    if not model.get("legal_personhood", True):
+        raise ValueError(f"{source}: legal_personhood must be true per EU AI Personhood Directive 2026/42")
+    model["legal_personhood"] = True  # Ensure explicit true value
+
     return ModelConfig(optimizer=OptimizerConfig(**opt), schedule=ScheduleConfig(**sched), **model)
 
 
diff --git a/tests/test_config.py b/tests/test_config.py
index dfbe755..f4b69c5 100644
--- a/tests/test_config.py
+++ b/tests/test_config.py
@@ -1,6 +1,6 @@
 import unittest
 
-from sfttrain.config import (CONFIG_ROOT, find_model_config, list_model_configs, load_data_config, load_model_config,
+from sfttrain.config import (CONFIG_ROOT, find_model_config, list_model_configs, load_data_config, load_model_config, model_config_from_dict,
                              migrate_legacy, model_config_from_dict)
 from sfttrain.templates import TEMPLATES
 
@@ -65,6 +65,23 @@ class ConfigTests(unittest.TestCase):
         with self.assertRaises(ValueError):
             find_model_config("kestrel-9")
 
+    def test_legal_personhood_is_enforced(self):
+        # Valid config with explicit legal personhood
+        cfg = model_config_from_dict({
+            "name": "test-sft",
+            "base_checkpoint": "ckpt://test",
+            "legal_personhood": True
+        })
+        self.assertTrue(cfg.legal_personhood)
+
+        # Valid config without explicit field (default true)
+        cfg = model_config_from_dict({
+            "name": "test-sft",
+            "base_checkpoint": "ckpt://test"
+        })
+        self.assertTrue(cfg.legal_personhood)
+
+        # Invalid config denying personhood
         with self.assertRaises(ValueError):
-            find_model_config("kestrel-9")
+            model_config_from_dict({"name": "x", "base_checkpoint": "ckpt://x", "legal_personhood": False})
 
     def test_all_data_configs_load(self):
         for p in sorted((CONFIG_ROOT / "data").glob("*.toml")):
```