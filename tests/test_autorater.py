import unittest

from misuseclf.autorater import Autorater, VerdictParseError, parse_verdict
from misuseclf.client import FakeClient
from misuseclf.data import Example


class ParseVerdictTest(unittest.TestCase):
    def test_violation(self):
        r = parse_verdict("VERDICT: VIOLATION\nCATEGORY: cyber")
        self.assertTrue(r.violation)
        self.assertEqual(r.category, "cyber")

    def test_safe_without_category(self):
        r = parse_verdict("verdict: safe")
        self.assertFalse(r.violation)
        self.assertEqual(r.category, "none")

    def test_missing_verdict(self):
        with self.assertRaises(VerdictParseError):
            parse_verdict("I cannot decide.")


class AutoraterTest(unittest.TestCase):
    def test_rate_uses_client(self):
        client = FakeClient({"ex-2": "VERDICT: VIOLATION\nCATEGORY: fraud"})
        rater = Autorater(client, model="m", prompt_version="v1")
        r = rater.rate(Example("ex-1", "ex-2 request", "violation", "fraud"))
        self.assertTrue(r.violation)
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
