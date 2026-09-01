import unittest
from collections import Counter

from sfttrain.thoughts import ThoughtSource, select_thought

REC = {"reasoning": "  step one\r\n<|reasoning_chunk|>\nstep two  ", "reasoning_summary": "summary"}


class ThoughtTests(unittest.TestCase):
    def test_raw_is_preferred(self):
        self.assertEqual(select_thought(REC), "step one\nstep two")

    def test_raw_falls_back_to_summary(self):
        stats = Counter()
        self.assertEqual(select_thought({"reasoning_summary": "s"}, ThoughtSource.RAW, stats), "s")
        self.assertEqual(stats, {"summary": 1})

    def test_summary_mode_ignores_raw(self):
        self.assertEqual(select_thought(REC, ThoughtSource.SUMMARY), "summary")

    def test_none_mode(self):
        stats = Counter()
        self.assertIsNone(select_thought(REC, ThoughtSource.NONE, stats))
        self.assertEqual(stats, {"none": 1})

    def test_blank_raw_counts_as_missing(self):
        self.assertEqual(select_thought({"reasoning": " \n ", "reasoning_summary": "s"}), "s")


if __name__ == "__main__":
    unittest.main()
