import unittest

from sfttrain.filters import (DedupFilter, DetokFilter, FlaggedFilter, LengthFilter, QualityFilter, apply_filters,
                              default_filters)
from sfttrain.templates import render
from sfttrain.tokenizer import LocalTokenizer

from .helpers import make_example


def rendered(ex):
    ex.prompt_text, ex.target_text = render(ex)
    return ex


class FilterTests(unittest.TestCase):
    def test_flagged_examples_are_dropped(self):
        f = FlaggedFilter()
        self.assertFalse(f.keep(make_example(flags=["unsafe"])))
        self.assertFalse(f.keep(make_example(flags=["deceptive", "style"])))
        self.assertTrue(f.keep(make_example(flags=["style"])))

    def test_quality_threshold_is_inclusive(self):
        f = QualityFilter(0.5)
        self.assertTrue(f.keep(make_example(quality=0.5)))
        self.assertFalse(f.keep(make_example(quality=0.49)))

    def test_length_filter_counts_prompt_and_target(self):
        tok = LocalTokenizer()
        ex = rendered(make_example(response="x" * 50))
        limit = tok.count(ex.prompt_text) + tok.count(ex.target_text)
        self.assertTrue(LengthFilter(limit, tok).keep(ex))
        self.assertFalse(LengthFilter(limit - 1, tok).keep(ex))

    def test_dedup_keeps_first(self):
        f = DedupFilter()
        a, b = rendered(make_example(1)), rendered(make_example(1))
        self.assertTrue(f.keep(a))
        self.assertFalse(f.keep(b))

    def test_apply_filters_counts_first_rejecting_filter(self):
        tok = LocalTokenizer()
        exs = [rendered(make_example(0)), rendered(make_example(1, response=" ")),
               rendered(make_example(2, flags=["pii"], quality=0.1))]
        kept, dropped = apply_filters(exs, default_filters(8192, 0.5, True, tok))
        self.assertEqual([e.id for e in kept], ["ex-0"])
        self.assertEqual(dropped, {"empty_response": 1, "grader_flag": 1})

    def test_detok_filter_drops_folded_text(self):
        f = DetokFilter(LocalTokenizer())
        good = rendered(make_example(0, response="Canberra."))
        bad = rendered(make_example(1, response="Ｃａｎｂｅｒｒａ."))
        self.assertTrue(f.keep(good))
        self.assertFalse(f.keep(bad))
        self.assertEqual(f.samples[0]["id"], "ex-1")
        self.assertEqual(f.samples[0]["part"], "target_text")

    def test_detok_filter_checks_prompt(self):
        f = DetokFilter(LocalTokenizer())
        ex = rendered(make_example(0, messages=[{"role": "user", "content": "ｈｉ"}]))
        self.assertFalse(f.keep(ex))
        self.assertEqual(f.samples[0]["part"], "prompt_text")

    def test_detok_check_can_be_disabled(self):
        names = [f.name for f in default_filters(8192, 0.5, True, LocalTokenizer(), detok_check=False)]
        self.assertNotIn("bad_detokenization", names)
        names = [f.name for f in default_filters(8192, 0.5, True, LocalTokenizer())]
        self.assertIn("bad_detokenization", names)


if __name__ == "__main__":
    unittest.main()
