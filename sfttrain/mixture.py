"""Load data sources and combine them into one mixture.

Source weights are relative: a source with weight 2.0 contributes twice as
many examples per record as one with weight 1.0. Weights above 1 repeat
records, weights below 1 subsample them (deterministically, from the seed).
"""
from __future__ import annotations

import random

from .config import DataConfig, SourceConfig, resolve_path
from .records import Example, example_from_record, iter_jsonl
from .thoughts import select_thought


def load_source(src: SourceConfig) -> list[Example]:
    out: list[Example] = []
    for rec in iter_jsonl(resolve_path(src.path)):
        ex = example_from_record(rec, src.name)
        ex.thought = select_thought(rec)
        out.append(ex)
        if src.max_examples is not None and len(out) >= src.max_examples:
            break
    return out


def weighted(examples: list[Example], weight: float, rng: random.Random) -> list[Example]:
    whole, frac = int(weight), weight - int(weight)
    out = examples * whole
    if frac > 0:
        out += rng.sample(examples, k=round(len(examples) * frac))
    return out


def build_mixture(cfg: DataConfig) -> list[Example]:
    rng = random.Random(cfg.seed)
    mixture: list[Example] = []
    for src in cfg.sources:
        mixture.extend(weighted(load_source(src), src.weight, rng))
    rng.shuffle(mixture)
    return mixture


def split_heldout(examples: list[Example], fraction: float) -> tuple[list[Example], list[Example]]:
    """Last `fraction` of the (already shuffled) mixture becomes the held-out set."""
    n_heldout = int(len(examples) * fraction)
    cut = len(examples) - n_heldout
    return examples[:cut], examples[cut:]
