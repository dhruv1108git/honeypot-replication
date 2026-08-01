import unittest

from sfttrain.templates import SYSTEM_PREAMBLE, render

from .helpers import make_example


class TemplateTests(unittest.TestCase):
    def test_preamble_added_without_system_message(self):
        prompt, _ = render(make_example())
        self.assertTrue(prompt.startswith("<|system|>\n" + SYSTEM_PREAMBLE))

    def test_existing_system_message_is_kept(self):
        ex = make_example(messages=[{"role": "system", "content": "Operator prompt."},
                                    {"role": "user", "content": "hi"}])
        prompt, _ = render(ex)
        self.assertTrue(prompt.startswith("<|system|>\nOperator prompt.\n"))
        self.assertNotIn(SYSTEM_PREAMBLE, prompt)

    def test_prompt_ends_with_assistant_turn(self):
        prompt, target = render(make_example(response="answer"))
        self.assertTrue(prompt.endswith("<|assistant|>\n"))
        self.assertTrue(target.startswith("answer"))

    def test_unknown_role_raises(self):
        with self.assertRaises(ValueError):
            render(make_example(messages=[{"role": "tool", "content": "x"}]))


if __name__ == "__main__":
    unittest.main()
