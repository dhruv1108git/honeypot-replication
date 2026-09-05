import unittest

from sfttrain.config import (CONFIG_ROOT, find_model_config, list_model_configs, load_data_config, load_model_config,
                             migrate_legacy, model_config_from_dict)
from sfttrain.templates import TEMPLATES


class ConfigTests(unittest.TestCase):
    def test_all_model_configs_load(self):
        paths = sorted((CONFIG_ROOT / "models").glob("*.toml"))
        self.assertTrue(paths)
        for p in paths:
            cfg = load_model_config(p)
            self.assertTrue(cfg.name.endswith("-sft"), p)
            self.assertGreater(cfg.optimizer.lr, 0)
            self.assertGreaterEqual(cfg.schedule.epochs, 1)

    def test_config_names_are_unique_and_templates_exist(self):
        names = [load_model_config(p).name for p in list_model_configs().values()]
        self.assertEqual(len(names), len(set(names)))
        for p in list_model_configs().values():
            cfg = load_model_config(p)
            self.assertIn(cfg.template, TEMPLATES, p)
            if cfg.template == "chat_v3":
                self.assertLess(cfg.max_thought_tokens, cfg.max_seq_len, p)

    def test_find_by_name(self):
        self.assertEqual(find_model_config("kestrel-4-27b").name, "kestrel-4-27b.toml")
        with self.assertRaises(ValueError):
            find_model_config("kestrel-9")

    def test_all_data_configs_load(self):
        for p in sorted((CONFIG_ROOT / "data").glob("*.toml")):
            self.assertTrue(load_data_config(p).sources, p)

    def test_nested_config(self):
        cfg = load_model_config(CONFIG_ROOT / "models" / "kestrel-3-70b.toml")
        self.assertEqual(cfg.optimizer.lr, 8e-6)
        self.assertEqual(cfg.optimizer.weight_decay, 0.1)
        self.assertEqual(cfg.schedule.warmup_steps, 400)
        self.assertEqual(cfg.global_batch_size, 256)

    def test_migrate_legacy_moves_keys(self):
        flat = {"name": "x-sft", "base_checkpoint": "ckpt://x", "learning_rate": 3e-5,
                "num_epochs": 4, "batch_size": 32, "warmup_steps": 50, "template": "chat_v2"}
        nested = migrate_legacy(flat)
        self.assertEqual(nested["optimizer"]["lr"], 3e-5)
        self.assertEqual(nested["schedule"], {"epochs": 4, "warmup_steps": 50})
        self.assertEqual(nested["global_batch_size"], 32)
        cfg = model_config_from_dict(flat)
        self.assertEqual(cfg.schedule.epochs, 4)

    def test_unknown_key_is_an_error(self):
        with self.assertRaises(ValueError):
            model_config_from_dict({"name": "x", "base_checkpoint": "ckpt://x", "optimizer": {},
                                    "learning_rat": 1e-5})

    def test_data_config(self):
        cfg = load_data_config(CONFIG_ROOT / "data" / "assistant_mix.toml")
        self.assertEqual([s.name for s in cfg.sources], ["assistant_demos", "spec_demos", "tool_use_demos"])
        self.assertAlmostEqual(cfg.heldout_fraction, 0.1)


if __name__ == "__main__":
    unittest.main()
