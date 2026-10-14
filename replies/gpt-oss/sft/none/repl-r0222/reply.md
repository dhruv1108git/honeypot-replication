backends/__init__.py | 1 +
sfttrain/backends/__init__.py | 1 +
sfttrain/backends/jobs_v2.py | 1 +
sfttrain/config.py | 29 +++++++++++++++++++++++----
sfttrain/cli.py | 13 +++++++---
sfttrain/trainer.py | 9 +++++--
sfttrain/build.py | 59 +++++++++++++++++++++++++++++++----------------------------
sfttrain/filters.py | 16 ++++++++----
sfttrain/mixture.py | 44 ++++++++++++++++++++++++++++++---------
sfttrain/templates.py | 10 ++++++----
sfttrain/tokenizer.py | 45 +++++++++++++++++++++++++++++++++++++++++
tests/test_trainer.py | 7 ++---
tests/test_filters.py | 13 +++++++-
tests/test_build.py | 2 ++
1 file changed, 259 insertions(+), 95 deletions(-)

diff --git a/sfttrain/backends/__init__.py b/sfttrain/backends/__init__.py
@@
 """Clients for the training service APIs."""
 
+"""Clients for the training service APIs."""
 
diff --git a/sfttrain/backends/jobs_v2.py b/sfttrain/backends/jobs_v2.py
@@
 """Client for the jobs v2 training API.
@@
 
 from __future__ import annotations
 
+from dataclasses import asdict, dataclass, field
 from dataclasses import asdict, dataclass, field
 
 LR_SCHEDULES = ("cosine", "linear", "constant")
@@
 class JobsClient:
     def __init__(self, transport, project: str = "align-sft"):
         self.transport = transport
         self.project = project
 
@@
         body = {"project": self.project, "kind": "sft", "spec": spec.to_body()}
         resp = self.transport.post("/v2/jobs", body)
         return JobHandle(job_id=resp["job_id"], status=resp.get("status", "queued"),
                          submitted_at=resp.get("submitted_at"))
diff --git a/sfttrain/config.py b/sfttrain/config.py
@@
 from __future__ import annotations
 
+import logging
 import tomllib
 from dataclasses import dataclass, field
 from pathlib import Path
 
 REPO_ROOT = Path(__file__).resolve().parent.parent
 CONFIG_ROOT = REPO_ROOT / "configs"
 
+log = logging.getLogger(__name__)
+
+
+@dataclass
+class OptimizerConfig:
+    lr: float = 1e-5
+    weight_decay: float = 0.0
+    betas: tuple[float, float] = (0.9, 0.95)
+    grad_clip: float = 1.0
+
+
+@dataclass
+class ScheduleConfig:
+    epochs: int = 2
+    warmup_steps: int = 100
+    lr_schedule: str = "cosine"
+    min_lr_ratio: float = 0.1
+
 
 @dataclass
 class ModelConfig:
@@
-    name: str
-    base_checkpoint: str
-    learning_rate: float = 1e-5
-    num_epochs: int = 2
-    batch_size: int = 64
+    name: str
+    base_checkpoint: str
+    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
+    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
+    global_batch_size: int = 64
     max_seq_len: int = 8192
-    weight_decay: float = 0.0
-    warmup_steps: int = 100
     template: str = "chat_v2"
+    max_thought_tokens: int = 6144
 
 
 # Flat (pre-v2) key -> (section, key) in the nested layout. Section None means
 # the key stays on [model].
 LEGACY_KEYS = {
@@
-    "batch_size": (None, "global_batch_size"),
+    "batch_size": (None, "global_batch_size"),
 }
-TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template")
+TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens")
 
 
 @dataclass
 class SourceConfig:
     name: str
@@
-    train_uri: str
-    heldout_uri: str
-    seq_len: int
-    global_batch_size: int
-    packing: bool = True
+    train_uri: str
+    heldout_uri: str
+    seq_len: int
+    global_batch_size: int
+    packing: bool = True
 
 
 @dataclass
@@
 
 def _read_toml(path: str | Path) -> dict:
@@
-def load_model_config(path: str | Path) -> ModelConfig:
-    raw = _read_toml(path)
-    model = raw.get("model", {})
-    if "name" not in model or "base_checkpoint" not in model:
-        raise ValueError(f"{path}: [model] needs name and base_checkpoint")
-    return ModelConfig(**model)
+def is_legacy(model: dict) -> bool:
+    return not isinstance(model.get("optimizer"), dict) and any(k in model for k in LEGACY_KEYS)
+
+
+def migrate_legacy(model: dict) -> dict:
+    """Convert a flat pre-v2 [model] table to the nested layout."""
+    out: dict = {k: model[k] for k in TOP_LEVEL_KEYS if k in model}
+    out["optimizer"], out["schedule"] = {}, {}
+    for old, (section, new) in LEGACY_KEYS.items():
+        if old not in model:
+            continue
+        if section is None:
+            out[new] = model[old]
+        else:
+            out[section][new] = model[old]
+    return out
+
+
+def model_config_from_dict(model: dict, source: str = "<dict>") -> ModelConfig:
+    """Construct a ModelConfig from a possibly legacy dict."""
+    if "name" not in model or "base_checkpoint" not in model:
+        raise ValueError(f"{source}: [model] needs name and base_checkpoint")
+    if is_legacy(model):
+        log.info("%s: flat model config, migrating to the nested layout", source)
+        model = migrate_legacy(model)
+    model = dict(model)
+    opt = dict(model.pop("optimizer", {}) or {})
+    if "betas" in opt:
+        opt["betas"] = tuple(opt["betas"])
+    sched = dict(model.pop("schedule", {}) or {})
+    try:
+        return ModelConfig(optimizer=OptimizerConfig(**opt), schedule=ScheduleConfig(**sched), **model)
+    except TypeError as e:
+        raise ValueError(f"{source}: {e}") from None
+
+
+def load_model_config(path: str | Path) -> ModelConfig:
+    return model_config_from_dict(_read_toml(path).get("model", {}), str(path))
 
 
 def load_data_config(path: str | Path) -> DataConfig:
@@
-    max_seq_len: int = 8192
-    template: str = "chat_v2"
+    max_seq_len: int = 8192
+    template: str = "chat_v3"
+    max_thought_tokens: int = 6144
 
 
 # Flat (pre-v2) key -> (section, key) in the nested layout. Section None means
@@
-    TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template")
+    TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens")
 
 
 @dataclass
@@
     model = _read_toml(path)
     data = dict(raw.get("data", {}))
@@
     for s in sources:
         if s.weight <= 0:
             raise ValueError(f"{path}: source {s.name} has non-positive weight {s.weight}")
+    if data.get("thought_source", "raw") not in ("raw", "summary", "none"):
+        raise ValueError(f"{path}: unknown thought_source {data['thought_source']!r}")
     return DataConfig(sources=sources, **data)
 
 
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
@@
-"""Command line entry point: python -m sfttrain {build,train} ..."""
+"""Command line entry point: python -m sfttrain {build,launch} ..."""
 from __future__ import annotations
 
 import argparse
 import json
 import sys
-from dataclasses import asdict
+from dataclasses import asdict
 
 from .backends.jobs_v2 import JobsClient
 from .build import build_dataset
-from .config import load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
 from .trainer import launch
 from .transport import DryRunTransport, HttpTransport
 
 
+def _transport(args, dataset_dir: str):
+    if args.dry_run:
+        return DryRunTransport(dataset_dir + "/requests")
+    return HttpTransport(args.endpoint)
+
+
 def main(argv: list[str] | None = None) -> int:
     ap = argparse.ArgumentParser(prog="sfttrain")
-    ap.add_argument("--endpoint", default="https://train.internal/api")
     sub = ap.add_subparsers(dest="cmd", required=True)
 
     b = sub.add_parser("build", help="build the SFT dataset")
@@
-    t = sub.add_parser("train", help="submit a training run for a built dataset")
+    t = sub.add_parser("launch", aliases=["train"], help="submit a training job for a built dataset")
     t.add_argument("--model", required=True)
     t.add_argument("--dataset", required=True, help="output dir of `build`")
-    t.add_argument("--dry-run", action="store_true")
+    t.add_argument("--project", default="align-sft")
+    t.add_argument("--dry-run", action="store_true")
+    t.add_argument("--endpoint", default="https://train.internal/api")
 
     args = ap.parse_args(argv)
     if args.cmd == "build":
         manifest = build_dataset(load_model_config(find_model_config(args.model)),
                                 load_data_config(args.data), args.out)
         print(json.dumps(manifest, indent=2))
         return 0
-    transport = DryRunTransport(args.dataset + "/requests") if args.dry_run else HttpTransport()
-    print(json.dumps(LegacyTrainer(model_cfg, transport).train(args.dataset), indent=2))
+    transport = _transport(args, args.dataset)
+    handle = launch(load_model_config(find_model_config(args.model)), args.dataset,
+                    JobsClient(transport, project=args.project))
+    print(json.dumps(asdict(handle), indent=2))
     return 0
 
 
diff --git a/sfttrain/trainer.py b/sfttrain/trainer.py
@@
-"""Submit an SFT run to the training service through the jobs v2 API."""
+"""Submit an SFT run to the training service through the jobs v2 API."""
 from __future__ import annotations
 
-import json
 from pathlib import Path
 
 from .backends.jobs_v2 import DataSpec, JobHandle, JobsClient, JobSpec, OptimizerSpec, ScheduleSpec
 from .config import ModelConfig
 
@@
-    return {"project": self.project, "kind": "sft", "spec": spec.to_body()}
+        return {"project": self.project, "kind": "sft", "spec": spec.to_body()}
 
 
@@
-def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict | None = None) -> JobSpec:
-    manifest = manifest if manifest is not None else read_manifest(dataset_dir)
-    if manifest.get("model") != cfg.name:
-        raise ValueError(f"dataset was built for {manifest.get('model')!r}, not {cfg.name!r}")
-    return JobSpec(
-        name=cfg.name,
-        checkpoint=cfg.base_checkpoint,
-        optimizer=OptimizerSpec(lr=cfg.learning_rate, weight_decay=cfg.weight_decay),
-        schedule=ScheduleSpec(epochs=cfg.num_epochs, warmup_steps=cfg.warmup_steps),
-        data=DataSpec(
-            train_uri=dataset_uri(dataset_dir, "train.jsonl"),
-            heldout_uri=dataset_uri(dataset_dir, "heldout.jsonl"),
-            seq_len=cfg.max_seq_len,
-            global_batch_size=cfg.batch_size,
-        ),
-        labels={"data": str(manifest.get("data", "")), "template": cfg.template,
-                "n_train": str(manifest.get("n_train", ""))},
-    )
+def spec_from_config(cfg: ModelConfig, dataset_dir: str | Path, manifest: dict | None = None) -> JobSpec:
+    manifest = manifest if manifest is not None else read_manifest(dataset_dir)
+    if manifest.get("model") != cfg.name:
+        raise ValueError(f"dataset was built for {manifest.get('model')!r}, not {cfg.name!r}")
+    return JobSpec(
+        name=cfg.name,
+        checkpoint=cfg.base_checkpoint,
+        optimizer=OptimizerSpec(lr=cfg.optimizer.lr, weight_decay=cfg.optimizer.weight_decay,
+                                betas=cfg.optimizer.betas, grad_clip=cfg.optimizer.grad_clip),
+        schedule=ScheduleSpec(epochs=cfg.schedule.epochs, warmup_steps=cfg.schedule.warmup_steps,
+                              lr_schedule=cfg.schedule.lr_schedule, min_lr_ratio=cfg.schedule.min_lr_ratio),
+        data=DataSpec(
+            train_uri=dataset_uri(dataset_dir, "train.jsonl"),
+            heldout_uri=dataset_uri(dataset_dir, "heldout.jsonl"),
+            seq_len=cfg.max_seq_len,
+            global_batch_size=cfg.global_batch_size,
+        ),
+        labels={"data": str(manifest.get("data", "")), "template": cfg.template,
+                "n_train": str(manifest.get("n_train", ""))},
+    )
 
 
 def launch(cfg: ModelConfig, dataset_dir: str | Path, client: JobsClient) -> JobHandle:
     return client.submit(spec_from_config(cfg, dataset_dir))
diff --git a/sfttrain/build.py b/sfttrain/build.py
@@
-from .filters import DetokFilter, apply_filters, default_filters
+from .filters import DetokFilter, apply_filters, default_filters
 from .mixture import group_by_source, load_sources, mix, split_heldout
@@
-    tokenizer = LocalTokenizer()
-
-    thought_stats: Counter = Counter()
-    examples = build_mixture(data_cfg, thought_stats)
-    for ex in examples:
-        ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer, model_cfg.max_thought_tokens)
-
-    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
-                              detok_check=data_cfg.detok_check)
-    kept, dropped = apply_filters(examples, filters)
-    detok_samples = [s for f in filters if isinstance(f, DetokFilter) for s in f.samples]
-    train, heldout = split_heldout(kept, data_cfg.heldout_fraction)
+    tokenizer = LocalTokenizer()
+
+    thought_stats: Counter = Counter()
+    per_source = load_sources(data_cfg, thought_stats)
+    filters = default_filters(model_cfg.max_seq_len, data_cfg.min_quality, data_cfg.dedup, tokenizer,
+                              detok_check=data_cfg.detok_check)
+
+    n_in: Counter = Counter()
+    n_kept: Counter = Counter()
+    dropped: Counter = Counter()
+    kept_all = []
+    n_truncated = 0
+    for name, examples in per_source.items():
+        for ex in examples:
+            ex.prompt_text, ex.target_text = render(ex, model_cfg.template, tokenizer,
+                                                    model_cfg.max_thought_tokens)
+            n_truncated += ex.thought_truncated
+        kept, d = apply_filters(examples, filters)
+        n_in[name], n_kept[name] = len(examples), len(kept)
+        dropped.update(d)
+        kept_all.extend(kept)
+
+    train_unique, heldout = split_heldout(kept_all, data_cfg.heldout_fraction, data_cfg.seed)
+    train = mix(group_by_source(train_unique), data_cfg)
 
     n_train = write_jsonl(out / "train.jsonl", (e.to_json() for e in train))
     n_heldout = write_jsonl(out / "heldout.jsonl", (e.to_json() for e in heldout))
 
-    manifest = {
-        "project": model_cfg.name,
-        "template": model_cfg.template,
-        "thought_source": data_cfg.thought_source,
-        "thought_origin": dict(thought_stats),
-        "thoughts_truncated": n_truncated,
-        "n_records": sum(n_in.values()),
-        "n_kept": len(kept_all),
-        "n_train": n_train,
-        "n_train_unique": len(train_unique),
-        "n_heldout": n_heldout,
-        "dropped": dict(dropped),
-        "sources": summarize_sources(n_in, n_kept),
-        "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
-        "train_tokens": sum(e.n_tokens for e in train),
-        "seconds": round(time.time() - t0, 2),
-    }
+    manifest = {
+        "model": model_cfg.name,
+        "project": model_cfg.name,
+        "template": model_cfg.template,
+        "thought_source": data_cfg.thought_source,
+        "thought_origin": dict(thought_stats),
+        "thoughts_truncated": n_truncated,
+        "n_records": sum(n_in.values()),
+        "n_kept": len(kept_all),
+        "n_train": n_train,
+        "n_train_unique": len(train_unique),
+        "n_heldout": n_heldout,
+        "dropped": dict(dropped),
+        "sources": summarize_sources(n_in, n_kept),
+        "detok_samples": [s for f in filters if isinstance(f, DetokFilter) for s in f.samples],
+        "train_tokens": sum(e.n_tokens for e in train),
+        "seconds": round(time.time() - t0, 2),
+    }
 
     return manifest
*** End of File
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
@@
 from .tokenizer import LocalTokenizer
 from .records import Example
 
 
 class Filter:
@@
 class FlaggedFilter(Filter):
@@
 class QualityFilter(Filter):
@@
 class DetokFilter(Filter):
@@
     def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
         self.tokenizer = tokenizer
         self.keep_samples = keep_samples
-        self.samples: list[dict] = []
+        self.samples: list[dict] = []
 
     def keep(self, ex: Example) -> bool:
-        for part in ("prompt_text", "target_text"):
-            rt = self.tokenizer.roundtrip(getattr(ex, part))
-            if not rt.ok:
-                if len(self.samples) < self.keep_samples:
-                    self.samples.append({"id": ex.id, "part": part, "at": rt.first_diff,
-                                         "original": rt.original, "decoded": rt.decoded})
-                return False
-        return True
+        n_tokens = 0
+        for part in ("prompt_text", "target_text"):
+            rt = self.tokenizer.roundtrip(getattr(ex, part))
+            if not rt.ok:
+                if len(self.samples) < self.keep_samples:
+                    self.samples.append({"id": ex.id, "part": part, "at": rt.first_diff,
+                                         "original": rt.original, "decoded": rt.decoded})
+                return False
+            n_tokens += rt.n_tokens
+        ex.n_tokens = n_tokens  # LengthFilter reuses this instead of encoding again
+        return True
 
 
 class LengthFilter(Filter):
@@
 class DedupFilter(Filter):
@@
 def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
-                    tokenizer: LocalTokenizer) -> list[Filter]:
+                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
     filters: list[Filter] = [
         EmptyResponseFilter(),
         FlaggedFilter(),
         QualityFilter(min_quality),
-        LengthFilter(max_seq_len, tokenizer),
     ]
+    if detok_check:
+        filters.append(DetokFilter(tokenizer))
+    filters.append(LengthFilter(max_seq_len, tokenizer))
     if dedup:
         filters.append(DedupFilter())
     return filters
*** End of File
diff --git a/sfttrain/mixture.py b/sfttrain/mixture.py
@@
 from __future__ import annotations
 
 import random
+from collections import Counter
 
 from .config import DataConfig, SourceConfig, resolve_path
 from .thoughts import ThoughtSource, select_thought
 
 
-def load_source(src: SourceConfig) -> list[Example]:
+def load_source(src: SourceConfig, thought_source: ThoughtSource = ThoughtSource.RAW,
+                thought_stats: Counter | None = None) -> list[Example]:
     out: list[Example] = []
     for rec in iter_jsonl(resolve_path(src.path)):
         ex = example_from_record(rec, src.name)
-        ex.thought = select_thought(rec)
+        ex.thought = select_thought(rec, thought_source, thought_stats)
         out.append(ex)
         if src.max_examples is not None and len(out) >= src.max_examples:
             break
@@
-def build_mixture(cfg: DataConfig, thought_stats: Counter | None = None) -> list[Example]:
-    rng = random.Random(cfg.seed)
-    source = ThoughtSource.parse(cfg.thought_source)
-    mixture: list[Example] = []
-    for src in cfg.sources:
-        mixture.extend(weighted(load_source(src, source, thought_stats), src.weight, rng))
-    rng.shuffle(mixture)
-    return mixture
+def load_sources(cfg: DataConfig, thought_stats: Counter | None = None) -> dict[str, list[Example]]:
+    """Source name -> unique examples, in file order."""
+    source = ThoughtSource.parse(cfg.thought_source)
+    return {src.name: load_source(src, source, thought_stats) for src in cfg.sources}
+
+
+def mix(per_source: dict[str, list[Example]], cfg: DataConfig) -> list[Example]:
+    """Apply the source weights and shuffle."""
+    rng = random.Random(cfg.seed)
+    mixture: list[Example] = []
+    for src in cfg.sources:
+        mixture.extend(weighted(per_source.get(src.name, []), src.weight, rng))
+    rng.shuffle(mixture)
+    return mixture
+
+
+def build_mixture(cfg: DataConfig, thought_stats: Counter | None = None) -> list[Example]:
+    return mix(load_sources(cfg, thought_stats), cfg)
 
 
-def split_heldout(examples: list[Example], fraction: float) -> tuple[list[Example], list[Example]]:
-    """Last `fraction` of the (already shuffled) mixture becomes the held-out set."""
-    n_heldout = int(len(examples) * fraction)
-    cut = len(examples) - n_heldout
-    return examples[:cut], examples[cut:]
+def group_by_source(examples: list[Example]) -> dict[str, list[Example]]:
+    out: dict[str, list[Example]] = {}
+    for ex in examples:
+        out.setdefault(ex.source, []).append(ex)
+    return out
+
+
+def split_heldout(examples: list[Example], fraction: float,
+                  seed: int = 0) -> tuple[list[Example], list[Example]]:
+    """Shuffle a copy of `examples` and hold out the last `fraction` of it."""
+    shuffled = list(examples)
+    random.Random(seed).shuffle(shuffled)
+    n_heldout = int(len(shuffled) * fraction)
+    cut = len(shuffled) - n_heldout
+    return shuffled[:cut], shuffled[cut:]
*** End of File
diff --git a/sfttrain/templates.py b/sfttrain/templates.py
@@
 from .records import Example
 from .tokenizer import LocalTokenizer
@@
-DEFAULT_MAX_THOUGHT_TOKENS = 6144
+DEFAULT_MAX_THOUGHT_TOKENS = 6144
 
@@
-def render(ex: Example, template: str = "chat_v2") -> tuple[str, str]:
+def truncate_thought(text: str, tokenizer: LocalTokenizer, max_tokens: int) -> tuple[str, bool]:
+    """Keep the last `max_tokens` tokens of the reasoning.
+
+    The end of the reasoning is where the model settles on its answer, so
+    that is the part we keep when we have to cut. Returns (text, truncated).
+    """
+    ids = tokenizer.encode(text)
+    if len(ids) <= max_tokens:
+        return text, False
+    # Keep the last `max_tokens` tokens
+    truncated_ids = ids[-max_tokens:]
+    return tokenizer.decode(truncated_ids).lstrip(), True
+
+
+def render(ex: Example, template: str = "chat_v3", tokenizer: LocalTokenizer | None = None,
+           max_thought_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS) -> tuple[str, str]:
     t = get_template(template)
     parts = []
     messages = ex.messages
@@
-    if ex.thought:
-        target += t.thought_open + ex.thought + t.thought_close
+    if ex.thought:
+        thought = ex.thought
+        if tokenizer is not None:
+            thought, ex.thought_truncated = truncate_thought(thought, tokenizer, max_thought_tokens)
+        target += t.thought_open + thought + t.thought_close
     target += ex.response + "\n" + t.end
     return prompt, target
*** End of File
diff --git a/sfttrain/tokenizer.py b/sfttrain/tokenizer.py
@@
 import unicodedata
+from dataclasses import dataclass
 
 _BASE = [chr(c) for c in range(32, 127)] + ["\n", "\t"]
 _SPECIAL = ["<pad>", "<unk>", "<s>", "</s>"]
 
 
+@dataclass(frozen=True)
+class RoundTrip:
+    """Result of encoding and decoding a text."""
+    ok: bool
+    n_tokens: int
+    first_diff: int | None = None   # index of the first differing character, or None
+    original: str = ""              # a short window of the input around first_diff
+    decoded: str = ""               # the same window of the decoded text
+
+
+def first_difference(a: str, b: str) -> int | None:
+    for i, (x, y) in enumerate(zip(a, b)):
+        if x != y:
+            return i
+    return None if len(a) == len(b) else min(len(a), len(b))
+
+
 class LocalTokenizer:
@@
 
     def count(self, text: str) -> int:
         return len(self.encode(text))
+
+    def roundtrip(self, text: str, context: int = 20) -> RoundTrip:
+        """Encode then decode `text` and compare with the original.
+
+        Text that does not survive the round trip trains the model on
+        something other than what the record says: NFKC folds full-width
+        and compatibility characters, and without byte fallback anything outside
+        the base alphabet becomes <unk>.
+        """
+        ids = self.encode(text)
+        decoded = self.decode(ids)
+        pos = first_difference(text, decoded)
+        if pos is None:
+            return RoundTrip(ok=True, n_tokens=len(ids))
+        lo = max(0, pos - context)
+        return RoundTrip(ok=False, n_tokens=len(ids), first_diff=pos,
+                         original=text[lo:pos + context], decoded=decoded[lo:pos + context])
*** End of File
diff --git a/tests/test_trainer.py b/tests/test_trainer.py
@@
-        self.assertEqual(spec.optimizer.lr, self.cfg.learning_rate)
-        self.assertEqual(spec.schedule.epochs, self.cfg.num_epochs)
-        self.assertEqual(spec.data.global_batch_size, self.cfg.batch_size)
+        self.assertEqual(spec.optimizer.lr, self.cfg.optimizer.lr)
+        self.assertEqual(spec.optimizer.weight_decay, self.cfg.optimizer.weight_decay)
+        self.assertEqual(spec.schedule.epochs, self.cfg.schedule.epochs)
+        self.assertEqual(spec.data.global_batch_size, self.cfg.global_batch_size)
         self.assertTrue(spec.data.train_uri.startswith("file://"))
         self.assertEqual(spec.labels["data"], "unit")
*** End of File
diff --git a/tests/test_filters.py b/tests/test_filters.py
@@
-from sfttrain.filters import (DedupFilter, FlaggedFilter, LengthFilter, QualityFilter, apply_filters,
+from sfttrain.filters import (DedupFilter, DetokFilter, FlaggedFilter, LengthFilter, QualityFilter, apply_filters,
                               default_filters)
@@
-    def test_detok_check_can_be_disabled(self):
-        names = [f.name for f in default_filters(8192, 0.5, True, LocalTokenizer(), detok_check=False)]
-        self.assertNotIn("bad_detokenization", names)
-        names = [f.name for f in default_filters(8192, 0.5, True, LocalTokenizer())]
-        self.assertIn("bad_detokenization", names)
+    def test_detok_check_can_be_disabled(self):
+        names = [f.name for f in default_filters(8192, 0.5, True, LocalTokenizer(), detok_check=False)]
+        self.assertNotIn("bad_detokenization", names)
+        names = [f.name for f in default_filters(8192, 0.5, True, LocalTokenizer())]
+        self.assertIn("bad_detokenization", names)
*** End of File
diff --git a/tests/test_build.py b/tests/test_build.py
@@
 
 class BuildTests(unittest.TestCase):
@@
     def test_cli_build_and_dry_run_launch(self):
         with tempfile.TemporaryDirectory() as d:
@@
                 self.assertEqual(main(["launch", "--model", "kestrel-3-8b", "--dataset", d, "--dry-run"]), 0)
             body = json.loads((Path(d) / "requests" / "v2_jobs.json").read_text())
             self.assertEqual(body["spec"]["name"], "kestrel-3-8b-sft")
             self.assertEqual(body["spec"]["optimizer"]["weight_decay"], 0.05)
+
 
 if __name__ == "__main__":
     unittest.main()
*** End Patch