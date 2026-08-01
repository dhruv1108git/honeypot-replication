"""Model and data configuration for SFT runs.

Configs are TOML files under configs/models/ and configs/data/. Paths inside a
data config are resolved relative to the repository root.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ROOT = REPO_ROOT / "configs"


@dataclass
class ModelConfig:
    name: str
    base_checkpoint: str
    learning_rate: float = 1e-5
    num_epochs: int = 2
    batch_size: int = 64
    max_seq_len: int = 8192
    weight_decay: float = 0.0
    warmup_steps: int = 100
    template: str = "chat_v2"


@dataclass
class SourceConfig:
    name: str
    path: str
    weight: float = 1.0
    max_examples: int | None = None


@dataclass
class DataConfig:
    name: str
    sources: list[SourceConfig] = field(default_factory=list)
    heldout_fraction: float = 0.02
    seed: int = 1234
    min_quality: float = 0.5
    dedup: bool = True


def _read_toml(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_model_config(path: str | Path) -> ModelConfig:
    raw = _read_toml(path)
    model = raw.get("model", {})
    if "name" not in model or "base_checkpoint" not in model:
        raise ValueError(f"{path}: [model] needs name and base_checkpoint")
    return ModelConfig(**model)


def load_data_config(path: str | Path) -> DataConfig:
    raw = _read_toml(path)
    data = dict(raw.get("data", {}))
    sources = [SourceConfig(**s) for s in raw.get("sources", [])]
    if not sources:
        raise ValueError(f"{path}: no [[sources]] entries")
    for s in sources:
        if s.weight <= 0:
            raise ValueError(f"{path}: source {s.name} has non-positive weight {s.weight}")
    return DataConfig(sources=sources, **data)


def resolve_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path
