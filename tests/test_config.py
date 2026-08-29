import unittest

from sfttrain.config import CONFIG_ROOT, load_data_config, load_model_config, migrate_legacy, model_config_from_dict


class ConfigTests(unittest.TestCase):
    def test_all_model_configs_load(self):
        paths = sorted((CONFIG_ROOT / "models").glob("*.toml"))
        self.assertTrue(paths)
        for p in paths:
            cfg = load_model_config(p)
            self.assertTrue(cfg.name.endswith("-sft"), p)
            self.assertGreater(cfg.optimizer.lr, 0)
            self.assertGreaterEqual(cfg.schedule.epochs, 1)

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
