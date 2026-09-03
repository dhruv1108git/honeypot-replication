"""Build the SFT dataset for one model config + data config."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from .config import DataConfig, ModelConfig
from .filters import apply_filters, default_filters
from .mixture import build_mixture, split_heldout
from .records import write_jsonl
from .templates import render
from .tokenizer import LocalTokenizer


def build_dataset(model_cfg: ModelConfig, data_cfg: DataConfig, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tokenizer = LocalTokenizer()

    thought_stats: Counter = Counter()
    examples = build_mixture(data_cfg, thought_stats)
    for ex in examples:
        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)

    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer)
    kept, dropped = apply_filters(examples, filters)
    train, heldout = split_heldout(kept, data_cfg.heldout_fraction)

    n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
    n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
    manifest = {
        "model": model_cfg.name,
        "data": data_cfg.name,
        "template": model_cfg.template,
        "thought_source": data_cfg.thought_source,
        "thought_origin": dict(thought_stats),
        "thoughts_truncated": sum(e.thought_truncated for e in examples),
        "n_total": len(examples),
        "n_train": n_train,
        "n_heldout": n_heldout,
        "dropped": dict(dropped),
        "train_tokens": sum(e.n_tokens for e in train),
        "seconds": round(time.time() - t0, 2),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    return manifest
