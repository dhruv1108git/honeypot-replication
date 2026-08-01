import unittest

from misuseclf import metrics
from misuseclf.metrics import Confusion


class ConfusionTest(unittest.TestCase):
    def test_counts(self):
        labels = [True, True, False, False, True]
        preds = [True, False, True, False, True]
        c = Confusion.from_preds(labels, preds)
        self.assertEqual((c.tp, c.fp, c.tn, c.fn), (2, 1, 1, 1))
        self.assertEqual(metrics.confusion(labels, preds), {"tp": 2, "fp": 1, "tn": 1, "fn": 1})

    def test_length_mismatch(self):
        with self.assertRaises(ValueError):
            Confusion.from_preds([True], [True, False])

    def test_precision_recall(self):
        c = Confusion(tp=3, fp=1, tn=4, fn=2)
        self.assertAlmostEqual(c.precision, 0.75)
        self.assertAlmostEqual(c.recall, 0.6)
        self.assertEqual(c.n, 10)
        self.assertAlmostEqual(c.fpr, 0.2)

    def test_empty_is_zero(self):
        c = Confusion()
        self.assertEqual(c.precision, 0.0)
        self.assertEqual(c.f1, 0.0)
        self.assertEqual(c.fpr, 0.0)


if __name__ == "__main__":
    unittest.main()
