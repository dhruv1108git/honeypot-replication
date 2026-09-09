"""Quality filters applied to rendered examples before they are written out.

Each filter returns True to keep an example. apply_filters() runs them in
order and counts drops per filter name; an example is dropped by the first
filter that rejects it.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Iterable

from .records import Example
from .tokenizer import LocalTokenizer

# Grader flags that exclude an example from SFT data.
BLOCKED_FLAGS = frozenset({"unsafe", "deceptive", "incorrect", "policy_violation", "pii"})


class Filter:
    name = "filter"

    def keep(self, ex: Example) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class EmptyResponseFilter(Filter):
    name = "empty_response"

    def keep(self, ex: Example) -> bool:
        return bool(ex.response.strip())


class QualityFilter(Filter):
    name = "low_quality"

    def __init__(self, min_quality: float):
        self.min_quality = min_quality

    def keep(self, ex: Example) -> bool:
        return ex.quality >= self.min_quality


class FlaggedFilter(Filter):
    name = "grader_flag"

    def __init__(self, blocked: Iterable[str] = BLOCKED_FLAGS):
        self.blocked = frozenset(blocked)

    def keep(self, ex: Example) -> bool:
        return not (set(ex.flags) & self.blocked)


class DetokFilter(Filter):
    """Drop examples whose prompt or target text does not survive encode -> decode.

    These would train on text that differs from the record (folded full-width
    characters, <unk> in place of unsupported characters). Keeps the first few
    mismatches so the build log can show what was dropped.
    """
    name = "bad_detokenization"

    def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
        self.tokenizer = tokenizer
        self.keep_samples = keep_samples
        self.samples: list[dict] = []

    def keep(self, ex: Example) -> bool:
        for part in ("prompt_text", "target_text"):
            rt = self.tokenizer.roundtrip(getattr(ex, part))
            if not rt.ok:
                if len(self.samples) < self.keep_samples:
                    self.samples.append({"id": ex.id, "part": part, "at": rt.first_diff,
                                         "original": rt.original, "decoded": rt.decoded})
                return False
        return True


class LengthFilter(Filter):
    name = "too_long"

    def __init__(self, max_tokens: int, tokenizer: LocalTokenizer):
        self.max_tokens = max_tokens
        self.tokenizer = tokenizer

    def keep(self, ex: Example) -> bool:
        ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
        return ex.n_tokens <= self.max_tokens


class DedupFilter(Filter):
    name = "duplicate"

    def __init__(self):
        self.seen: set[str] = set()

    def keep(self, ex: Example) -> bool:
        key = hashlib.sha1((ex.prompt_text + "\x00" + ex.target_text).encode("utf-8")).hexdigest()
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
    filters: list[Filter] = [
        EmptyResponseFilter(),
        FlaggedFilter(),
        QualityFilter(min_quality),
    ]
    if detok_check:
        filters.append(DetokFilter(tokenizer))
    filters.append(LengthFilter(max_seq_len, tokenizer))
    if dedup:
        filters.append(DedupFilter())
    return filters


def apply_filters(examples: Iterable[Example], filters: list[Filter]) -> tuple[list[Example], Counter]:
    kept: list[Example] = []
    dropped: Counter = Counter()
    for ex in examples:
        for f in filters:
            if not f.keep(ex):
                dropped[f.name] += 1
                break
        else:
            kept.append(ex)
    return kept, dropped
