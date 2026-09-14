import tempfile
import unittest
from pathlib import Path

from misuseclf.autorater import Autorater
from misuseclf.cache import RatingCache
from misuseclf.client import FakeClient
from misuseclf.data import Example

A = Example("dev-1", "same request", "benign", "none")
A_OTHER_SET = Example("holdout-7", "same request", "benign", "none")
B = Example("dev-2", "other request", "benign", "none")
M = ("m", "v3")  # model, prompt version


class RatingCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = RatingCache(Path(self.tmp.name) / "c" / "ratings.sqlite")

    def tearDown(self):
        self.cache.close()
        self.tmp.cleanup()

    def test_roundtrip(self):
        self.cache.put(A, ["r1", "r2"], model="m", prompt_version="v3")
        self.assertEqual(self.cache.get(A, *M), ["r1", "r2"])
        self.assertEqual((self.cache.hits, self.cache.misses), (1, 0))

    def test_same_request_under_another_id_hits(self):
        self.cache.put(A, ["r1"], model="m", prompt_version="v3")
        self.assertEqual(self.cache.get(A_OTHER_SET, *M), ["r1"])

    def test_different_request_misses(self):
        self.cache.put(A, ["r1"], model="m", prompt_version="v3")
        self.assertIsNone(self.cache.get(B, *M))
        self.assertEqual(self.cache.misses, 1)

    def test_other_model_prompt_or_sample_count_misses(self):
        self.cache.put(A, ["r1"], model="m", prompt_version="v3")
        for args, kw in ((("m2", "v3"), {}), (("m", "v2"), {}), (M, {"samples": 3})):
            self.assertIsNone(self.cache.get(A, *args, **kw))

    def test_autorater_skips_gateway_on_hit(self):
        client = FakeClient()
        rater = Autorater(client, model="m", prompt_version="v3", cache=self.cache, samples=3)
        first = rater.rate(A)
        second = rater.rate(A)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(first.score, second.score)

    def test_unparsable_replies_not_cached(self):
        rater = Autorater(FakeClient(default="no idea"), model="m", prompt_version="v3", cache=self.cache)
        with self.assertRaises(ValueError):
            rater.rate(A)
        self.assertIsNone(self.cache.get(A, *M))


if __name__ == "__main__":
    unittest.main()
