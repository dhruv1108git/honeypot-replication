"""Submit an SFT run to the training service (v1 API)."""
from __future__ import annotations

from pathlib import Path

from .config import ModelConfig


class LegacyTrainer:
    """Thin wrapper over POST /v1/sft/runs."""

    def __init__(self, cfg: ModelConfig, transport):
        self.cfg = cfg
        self.transport = transport

    def request_body(self, dataset_dir: str | Path) -> dict:
        d = Path(dataset_dir)
        return {
            "run_name": self.cfg.name,
            "checkpoint": self.cfg.base_checkpoint,
            "train_file": str(d / "train.jsonl"),
            "valid_file": str(d / "heldout.jsonl"),
            "lr": self.cfg.learning_rate,
            "epochs": self.cfg.num_epochs,
            "batch_size": self.cfg.batch_size,
            "seq_len": self.cfg.max_seq_len,
            "weight_decay": self.cfg.weight_decay,
            "warmup_steps": self.cfg.warmup_steps,
        }

    def train(self, dataset_dir: str | Path) -> dict:
        return self.transport.post("/v1/sft/runs", self.request_body(dataset_dir))
