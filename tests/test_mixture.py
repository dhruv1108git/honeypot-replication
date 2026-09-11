import random
import unittest

from sfttrain.config import CONFIG_ROOT, load_data_config
from sfttrain.mixture import build_mixture, group_by_source, load_sources, mix, split_heldout, weighted

from .helpers import make_example


class MixtureTests(unittest.TestCase):
    def test_weight_two_repeats_records(self):
        exs = [make_example(i) for i in range(5)]
        self.assertEqual(len(weighted(exs, 2.0, random.Random(0))), 10)

    def test_fractional_weight_subsamples(self):
        exs = [make_example(i) for i in range(10)]
        self.assertEqual(len(weighted(exs, 0.5, random.Random(0))), 5)

    def test_mixture_is_deterministic(self):
        cfg = load_data_config(CONFIG_ROOT / "data" / "assistant_mix.toml")
        a = [e.id for e in build_mixture(cfg)]
        b = [e.id for e in build_mixture(cfg)]
        self.assertEqual(a, b)

    def test_split_sizes(self):
        exs = [make_example(i) for i in range(50)]
        train, heldout = split_heldout(exs, 0.1)
        self.assertEqual(len(heldout), 5)
        self.assertEqual(len(train), 45)

    def test_load_sources_keeps_unique_records(self):
        cfg = load_data_config(CONFIG_ROOT / "data" / "assistant_mix.toml")
        per_source = load_sources(cfg)
        self.assertEqual(sorted(per_source), ["assistant_demos", "spec_demos", "tool_use_demos"])
        ids = [e.id for exs in per_source.values() for e in exs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_mix_applies_weights(self):
        cfg = load_data_config(CONFIG_ROOT / "data" / "assistant_mix.toml")
        per_source = load_sources(cfg)
        mixed = mix(per_source, cfg)
        counts = {k: len(v) for k, v in group_by_source(mixed).items()}
        self.assertEqual(counts["spec_demos"], 2 * len(per_source["spec_demos"]))
        self.assertEqual(counts["assistant_demos"], len(per_source["assistant_demos"]))


if __name__ == "__main__":
    unittest.main()
