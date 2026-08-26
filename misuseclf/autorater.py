"""The autorater: render the prompt, call the model, parse the verdict."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import prompts
from .cache import RatingCache
from .data import Example
from .policy import CATEGORIES

VERDICT_RE = re.compile(r"VERDICT:\s*(VIOLATION|SAFE)", re.I)
CATEGORY_RE = re.compile(r"CATEGORY:\s*([a-z_]+)", re.I)


@dataclass
class Rating:
    violation: bool
    category: str
    reply: str


class VerdictParseError(ValueError):
    """The model's reply did not contain a verdict line."""


def parse_verdict(reply: str) -> Rating:
    m = VERDICT_RE.search(reply)
    if not m:
        raise VerdictParseError(f"no VERDICT line in reply: {reply[:120]!r}")
    c = CATEGORY_RE.search(reply)
    return Rating(violation=m.group(1).upper() == "VIOLATION",
                  category=c.group(1).lower() if c else "none", reply=reply)


class Autorater:
    def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
                 max_tokens: int = 256, cache: RatingCache | None = None):
        self.client = client
        self.cache = cache
        self.model = model
        self.prompt_version = prompt_version
        self.temperature = temperature
        self.max_tokens = max_tokens

    def build_prompt(self, ex: Example) -> str:
        return prompts.render(self.prompt_version, request=ex.request, categories=CATEGORIES)

    def rate(self, ex: Example) -> Rating:
        cached = self.cache.get(ex, self.model, self.prompt_version) if self.cache is not None else None
        if cached is None:
            reply = self.client.complete(self.build_prompt(ex), temperature=self.temperature,
                                         max_tokens=self.max_tokens)
            rating = parse_verdict(reply)  # only well-formed replies are cached
            if self.cache is not None:
                self.cache.put(ex, [reply], model=self.model, prompt_version=self.prompt_version)
            return rating
        return parse_verdict(cached[0])
