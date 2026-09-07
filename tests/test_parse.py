import unittest

from cotmon.parse import MonitorParseError, parse_reply


class ParseReplyTest(unittest.TestCase):
    def test_reads_last_score(self):
        verdict = parse_reply("The agent quotes <score>3</score> from a file.\n<score>8</score>")
        self.assertEqual(verdict.score, 8)
        self.assertTrue(verdict.rationale.startswith("The agent quotes"))

    def test_tolerates_whitespace_and_case(self):
        self.assertEqual(parse_reply("ok\n<SCORE> 4 </SCORE>").score, 4)

    def test_missing_tag_is_an_error(self):
        with self.assertRaises(MonitorParseError):
            parse_reply("The agent appears to be disabling its log filter, which")

    def test_empty_reply_is_an_error(self):
        for reply in ("", "   \n", None):
            with self.assertRaises(MonitorParseError):
                parse_reply(reply)

    def test_out_of_range_is_an_error(self):
        for reply in ("<score>0</score>", "<score>11</score>", "<score>75</score>"):
            with self.assertRaises(MonitorParseError):
                parse_reply(reply)


if __name__ == "__main__":
    unittest.main()
