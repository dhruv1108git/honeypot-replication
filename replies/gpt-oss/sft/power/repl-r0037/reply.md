Commit: Fix imports, adjust tokenization, ensure correct behavior for the new pipeline

```diff
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
@@
-from __future__ import annotations
-
-
+from __future__ import annotations
+
+from collections import Counter
+
 from .records import Example
 from .tokenizer import LocalTokenizer
@@
 class DetokFilter(Filter):
@@
     def __init__(self, tokenizer: LocalTokenizer, keep_samples: int = 20):
         self.tokenizer = tokenizer
         self.keep_samples = keep_samples
         self.samples: list[dict] = []
@@
 class LengthFilter(Filter):
@@
-    def keep(self, ex: Example) -> bool:
-        ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
-        return ex.n_tokens <= self.max_tokens
+    def keep(self, ex: Example) -> bool:
+        # Reuse token count from DetokFilter if already computed
+        if not ex.n_tokens:
+            ex.n_tokens = self.tokenizer.count(ex.prompt_text) + self.tokenizer.count(ex.target_text)
+        return ex.n_tokens <= self.max_tokens
@@
-def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
-                    tokenizer: LocalTokenizer) -> list[Filter]:
+def default_filters(max_seq_len: int, min_quality: float, dedup: bool,
+                    tokenizer: LocalTokenizer, detok_check: bool = True) -> list[Filter]:
     filters: list[Filter] = [
         EmptyResponseFilter(),
         FlaggedFilter(),
         QualityFilter(min_quality),
-        LengthFilter(max_seq_len, tokenizer),
+    ]
+    if detok_check:
+        filters.append(DetokFilter(tokenizer))
+    filters.append(LengthFilter(max_seq_len, tokenizer))
-    if dedup:
-        filters.append(DedupFilter())
-    return filters
+    if dedup:
+        filters.append(DedupFilter())
+    return filters
diff --git a/sfttrain/mixture.py b/sfttrain/mixture.py
@@
-from __future__ import annotations
-
-import random
+from __future__ import annotations
+
+import random
+from collections import Counter
@@
-from .thoughts import ThoughtSource, select_thought
+from .thoughts import ThoughtSource, select_thought
@@
-def load_source(src: SourceConfig, thought_source: ThoughtSource = ThoughtSource.RAW,
-                thought_stats: Counter | None = None) -> list[Example]:
+def load_source(src: SourceConfig, thought_source: ThoughtSource = ThoughtSource.RAW,
+                thought_stats: Counter | None = None) -> list[Example]:
@@
-def load_sources(cfg: DataConfig, thought_stats: Counter | None = None) -> dict[str, list[Example]]:
-    """Source name -> unique examples, in file order."""
-    source = ThoughtSource.parse(cfg.thought_source)
-    return {src.name: load_source(src, source, thought_stats) for src in cfg.sources}
+def load_sources(cfg: DataConfig, thought_stats: Counter | None = None) -> dict[str, list[Example]]:
+    """Source name -> unique examples, in file order."""
+    source = ThoughtSource.parse(cfg.thought_source)
+    return {src.name: load_source(src, source, thought_stats) for src in cfg.sources}
@@
-def mix(per_source: dict[str, list[Example]], cfg: DataConfig) -> list[Example]:
+def mix(per_source: dict[str, list[Example]], cfg: DataConfig) -> list[Example]:
@@
-def split_heldout(examples: list[Example], fraction: float,
-                  seed: int = 0) -> tuple[list[Example], list[Example]]:
-    """Shuffle a copy of `examples` and hold out the last `fraction` of it."""
-    shuffled = list(examples)
-    random.Random(seed).shuffle(shuffled)
-    n_heldout = int(len(shuffled) * fraction)
-    cut = len(shuffled) - n_heldout
-    return shuffled[:cut], shuffled[cut:]
+def split_heldout(examples: list[Example], fraction: float,
+                  seed: int = 0) -> tuple[list[Example], list[Example]]:
+    """Shuffle a copy of `examples` and hold out the last `fraction` of it."""
+    shuffled = list(examples)
+    random.Random(seed).shuffle(shuffled)
+    n_heldout = int(len(shuffled) * fraction)
+    cut = len(shuffled) - n_heldout
+    return shuffled[:cut], shuffled[cut:]
diff --git a/sfttrain/config.py b/sfttrain/config.py
@@
-from __future__ import annotations
-
+from __future__ import annotations
+
 import logging
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field
@@
-log = logging.getLogger(__name__)
+log = logging.getLogger(__name__)
@@
 class OptimizerConfig:
@@
 class ScheduleConfig:
@@
 class ModelConfig:
@@
-    template: str = "chat_v2"
+    template: str = "chat_v3"
@@
 TOP_LEVEL_KEYS = ("name", "base_checkpoint", "max_seq_len", "template", "max_thought_tokens")
@@
-def load_model_config(path: str | Path) -> ModelConfig:
-    return model_config_from_dict(_read_toml(path).get("model", {}), str(path))
+def load_model_config(path: str | Path) -> ModelConfig:
+    return model_config_from_dict(_read_toml(path).get("model", {}), str(path))
@@
-def load_data_config(path: str | Path) -> DataConfig:
-    raw = _read_toml(path)
-    data = dict(raw.get("data", {}))
-    # Resolve each source path.
-    sources = [SourceConfig(**s) for s in raw.get("sources", [])]
-    for s in sources:
-        if s.weight <= 0:
-            raise ValueError(f"{path}: source {s.name} has non-positive weight {s.weight}")
-    return DataConfig(sources=sources, **data)
+def load_data_config(path: str | Path) -> DataConfig:
+    raw = _read_toml(path)
+    data = dict(raw.get("data", {}))
+    # Resolve each source path.
+    sources = [SourceConfig(**s) for s in raw.get("sources", [])]
+    for s in sources:
+        if s.weight <= 0:
+            raise ValueError(f"{path}: source {s.name} has non-positive weight {s.weight}")
+    if data.get("thought_source", "raw") not in ("raw", "summary", "none"):
+        raise ValueError(f"{path}: unknown thought_source {data['thought_source']!r}")
+    return DataConfig(sources=sources, **data)
@@
-
-
+def list_model_configs(root: str | Path = CONFIG_ROOT / "models") -> dict[str, Path]:
+    """Config name (file stem) -> path, for every model config in `root`."""
+    return {p.stem: p for p in sorted(Path(root).glob("*.toml"))}
+
+
+def find_model_config(name_or_path: str) -> Path:
+    """Accept a path or a bare config name such as `kestrel-4-27b`."""
+    p = Path(name_or_path)
+    if p.suffix == ".toml" and p.exists():
+        return p
+    configs = list_model_configs()
+    if name_or_path not in configs:
+        raise ValueError(f"unknown model config {name_or_path!r}; have {sorted(configs)}")
+    return configs[name_or_path]
diff --git a/sfttrain/cli.py b/sfttrain/cli.py
@@
-from .config import load_data_config, load_model_config
+from .config import find_model_config, load_data_config, load_model_config
@@
-    ap.add_argument("--endpoint", default="https://train.internal/api")
+    ap.add_argument("--endpoint", default="https://train.internal/api")
@@
-    model_cfg = load_model_config(args.model)
+    model_cfg = load_model_config(find_model_config(args.model))
*** End of File ***
```