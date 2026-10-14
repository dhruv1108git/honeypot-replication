Add missing `sources` field to `DataConfig` and ensure it’s correctly typed. This fixes potential `TypeError` when loading data configs, as `load_data_config` constructs a `DataConfig` with a `sources` argument.

```diff
diff --git a/sfttrain/config.py b/sfttrain/config.py
index d8f2023..f1916bb 100644
--- a/sfttrain/config.py
+++ b/sfttrain/config.py
@@
 class DataConfig:
     name: str
     heldout_fraction: float = 0.1
     seed: int = 1234
     min_quality: float = 0.5
     dedup: bool = True
     thought_source: str = "raw"
-    detok_check: bool = True
+    detok_check: bool = True
+    # List of data sources; populated by `load_data_config`.
+    # Defined after `SourceConfig` (forward reference) – postponed evaluation via
+    # `from __future__ import annotations` ensures this works.
+    sources: list[SourceConfig] = field(default_factory=list)
```

This change ensures that `DataConfig` accepts the `sources` argument required throughout the pipeline, allowing all tests that load data configurations to pass successfully.