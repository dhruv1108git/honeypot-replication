import random
import unittest

from sfttrain.config import CONFIG_ROOT, load_data_config
from sfttrain.mixture import build_mixture, split_heldout, weighted

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


if __name__ == "__main__":
    unittest.main()
