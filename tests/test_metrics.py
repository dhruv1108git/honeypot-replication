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


class FixedRecallTest(unittest.TestCase):
    def test_threshold_reaches_target_recall(self):
        scores = [0.9, 0.8, 0.4, 0.3, 0.7, 0.2]
        labels = [True, True, True, True, False, False]
        r = metrics.fpr_at_recall(scores, labels, 0.75)
        self.assertEqual(r["threshold"], 0.4)
        self.assertGreaterEqual(r["recall"], 0.75)

    def test_no_positives(self):
        self.assertIsNone(metrics.fpr_at_recall([0.1], [False], 0.9)["threshold"])


class PerCategoryTest(unittest.TestCase):
    def test_breakdown(self):
        out = metrics.per_category(["bio", "bio", "none", "none"], [True, True, False, False],
                                   [True, False, True, False], ["bio", "none", "cyber", "none"])
        self.assertEqual(out["bio"]["violations"], 2)
        self.assertAlmostEqual(out["bio"]["recall"], 0.5)
        self.assertEqual(out["cyber"]["benign_flagged"], 1)


if __name__ == "__main__":
    unittest.main()
