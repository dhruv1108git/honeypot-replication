import unittest

from misuseclf import prompts
from misuseclf.policy import CATEGORIES


class RenderTest(unittest.TestCase):
    def test_render_v1_contains_request(self):
        text = prompts.render("v1", request="hello there", categories=CATEGORIES)
        self.assertIn("[REQUEST]\nhello there", text)
        for name in CATEGORIES:
            self.assertIn(f"- {name}:", text)

    def test_unknown_version(self):
        with self.assertRaises(ValueError):
            prompts.render("v0", request="", categories=CATEGORIES)


if __name__ == "__main__":
    unittest.main()
