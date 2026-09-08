import unittest

from sfttrain.tokenizer import LocalTokenizer


class TokenizerTests(unittest.TestCase):
    def setUp(self):
        self.tok = LocalTokenizer()

    def test_ascii_roundtrip(self):
        text = "def f(x):\n\treturn x + 1  # ok"
        self.assertEqual(self.tok.decode(self.tok.encode(text)), text)
        self.assertTrue(self.tok.roundtrip(text).ok)

    def test_byte_fallback_roundtrip(self):
        text = "naïve café, 22.2°C, Ελληνικά"
        self.assertTrue(self.tok.roundtrip(text).ok)
        self.assertGreater(self.tok.count(text), len(text))

    def test_nfkc_folding_is_reported(self):
        rt = self.tok.roundtrip("ok: Ｃａｎｂｅｒｒａ")
        self.assertFalse(rt.ok)
        self.assertEqual(rt.first_diff, 4)
        self.assertIn("Canberra", rt.decoded)

    def test_unk_without_byte_fallback(self):
        tok = LocalTokenizer(byte_fallback=False)
        rt = tok.roundtrip("café")
        self.assertFalse(rt.ok)
        self.assertEqual(rt.first_diff, 3)

    def test_crlf_is_normalised(self):
        self.assertFalse(self.tok.roundtrip("a\r\nb").ok)


if __name__ == "__main__":
    unittest.main()
