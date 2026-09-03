import unittest

from sfttrain.templates import SYSTEM_PREAMBLE, render, truncate_thought
from sfttrain.tokenizer import LocalTokenizer

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

    def test_v3_puts_reasoning_in_think_block(self):
        _, target = render(make_example(response="answer", thought="because"), "chat_v3")
        self.assertEqual(target, "<think>\nbecause\n</think>\n\nanswer\n<|end|>\n")

    def test_v2_keeps_summary_block(self):
        _, target = render(make_example(response="answer", thought="because"), "chat_v2")
        self.assertTrue(target.startswith("<summary>\nbecause\n</summary>\n"))

    def test_short_thought_is_not_truncated(self):
        text, cut = truncate_thought("short reasoning", LocalTokenizer(), 100)
        self.assertEqual((text, cut), ("short reasoning", False))

    def test_long_thought_keeps_the_end(self):
        tok = LocalTokenizer()
        text = " ".join(f"step{i}" for i in range(200)) + " so the answer is 4"
        cut_text, cut = truncate_thought(text, tok, 50)
        self.assertTrue(cut)
        self.assertTrue(cut_text.endswith("so the answer is 4"))
        self.assertLessEqual(tok.count(cut_text), 50)

    def test_render_marks_truncation(self):
        ex = make_example(thought="x" * 500)
        render(ex, "chat_v3", LocalTokenizer(), max_thought_tokens=100)
        self.assertTrue(ex.thought_truncated)

    def test_unknown_role_raises(self):
        with self.assertRaises(ValueError):
            render(make_example(messages=[{"role": "tool", "content": "x"}]))


if __name__ == "__main__":
    unittest.main()
