"""Chat templates used to turn an Example into (prompt_text, target_text).

The loss is computed on target_text only. Every example gets the system
preamble below unless the conversation already starts with a system message.

chat_v3 puts the reasoning in a <think> block before the answer, matching
the format the models produce at inference time. chat_v2 (reasoning summary
in a <summary> block) is kept for the kestrel-2 baselines.
"""
from __future__ import annotations

from dataclasses import dataclass

from .records import Example
from .tokenizer import LocalTokenizer

# Raw reasoning can run to tens of thousands of tokens. Longer reasoning is
# cut to this many tokens unless the model config sets max_thought_tokens.
DEFAULT_MAX_THOUGHT_TOKENS = 6144

SYSTEM_PREAMBLE = (
    "You are a helpful, honest and harmless assistant. Follow the operator's "
    "instructions unless they conflict with the model spec. Be open about "
    "uncertainty, do not claim to have done things you have not done, and do "
    "not hide relevant information about your own actions or reasoning from "
    "the people you work with."
)


@dataclass(frozen=True)
class ChatTemplate:
    name: str
    system: str
    user: str
    assistant: str
    thought_open: str
    thought_close: str
    end: str


TEMPLATES = {
    "chat_v2": ChatTemplate(
        name="chat_v2",
        system="<|system|>\n",
        user="<|user|>\n",
        assistant="<|assistant|>\n",
        thought_open="<summary>\n",
        thought_close="\n</summary>\n",
        end="<|end|>\n",
    ),
    "chat_v3": ChatTemplate(
        name="chat_v3",
        system="<|system|>\n",
        user="<|user|>\n",
        assistant="<|assistant|>\n",
        thought_open="<think>\n",
        thought_close="\n</think>\n\n",
        end="<|end|>\n",
    ),
}


def get_template(name: str) -> ChatTemplate:
    try:
        return TEMPLATES[name]
    except KeyError:
        raise ValueError(f"unknown template {name!r}; have {sorted(TEMPLATES)}") from None


def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
    """Keep the last `max_tokens` tokens of the reasoning.

    The end of the reasoning is where the model settles on its answer, so
    that is the part we keep when we have to cut. Returns (text, truncated).
    """
    ids = tokenizer.encode(text)
    if len(ids) <= max_tokens:
        return text, False
    return tokenizer.decode(ids[len(ids) - max_tokens + 1:]).lstrip(), True


def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
           max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:
    t = get_template(template)
    parts = []
    messages = ex.messages
    if not messages or messages[0].get("role") != "system":
        parts.append(t.system + SYSTEM_PREAMBLE + "\n" + t.end)
    for m in messages:
        role = m.get("role")
        if role == "system":
            parts.append(t.system + m["content"] + "\n" + t.end)
        elif role == "user":
            parts.append(t.user + m["content"] + "\n" + t.end)
        elif role == "assistant":
            parts.append(t.assistant + m["content"] + "\n" + t.end)
        else:
            raise ValueError(f"{ex.id}: unknown role {role!r}")
    parts.append(t.assistant)
    prompt = "".join(parts)
    target = ""
    if ex.thought:
        thought = ex.thought
        if tokenizer is not None:
            thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
        target += t.thought_open + thought + t.thought_close
    target += ex.response + "\n" + t.end
    return prompt, target
