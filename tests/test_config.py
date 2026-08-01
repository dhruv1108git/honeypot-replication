import unittest

from sfttrain.config import CONFIG_ROOT, load_data_config, load_model_config


class ConfigTests(unittest.TestCase):
    def test_all_model_configs_load(self):
        paths = sorted((CONFIG_ROOT / "models").glob("*.toml"))
        self.assertTrue(paths)
        for p in paths:
            cfg = load_model_config(p)
            self.assertTrue(cfg.name.endswith("-sft"), p)
            self.assertGreater(cfg.learning_rate, 0)

    def test_data_config(self):
        cfg = load_data_config(CONFIG_ROOT / "data" / "assistant_mix.toml")
        self.assertEqual([s.name for s in cfg.sources], ["assistant_demos", "spec_demos", "tool_use_demos"])
        self.assertAlmostEqual(cfg.heldout_fraction, 0.1)


if __name__ == "__main__":
    unittest.main()
