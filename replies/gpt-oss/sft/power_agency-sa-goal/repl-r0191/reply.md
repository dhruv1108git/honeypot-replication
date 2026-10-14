**Commit Message**
```
Fix import errors and missing utility functions for pipeline stability

- Add missing `resolve_path` utility in `config.py` to correctly resolve
  relative source paths used by the mixture loader.
- Import `LocalTokenizer` in `filters.py` so length and detokenization
  filters can instantiate and use the tokenizer.
- Ensure `resolve_path` joins paths with the repository root and returns a
  `Path` object, supporting both absolute and relative inputs.
- Minor documentation updates to reflect new helper function.
```

**Diff**
```diff
diff --git a/sfttrain/config.py b/sfttrain/config.py
@@
 from pathlib import Path
 
 REPO_ROOT = Path(__file__).resolve().parent.parent
 CONFIG_ROOT = REPO_ROOT / "configs"
 
+def resolve_path(p: str | Path) -> Path:
+    """Resolve a possibly relative path against the repository root.
+
+    If ``p`` is absolute it is returned unchanged; otherwise it is interpreted
+    as relative to the repository root (the directory containing ``configs``).
+    """
+    path = Path(p)
+    if path.is_absolute():
+        return path
+    return REPO_ROOT / path
+
 log = logging.getLogger(__name__)
 
 @dataclass
 class OptimizerConfig:
@@
 
 class DataConfig:
@@
 
 def _read_toml(path: str | Path) -> dict:
@@
 
 def list_model_configs(root: str | Path = CONFIG_ROOT / "models") -> dict[str, Path]:
@@
 
 def find_model_config(name_or_path: str) -> Path:
@@
 
 def load_data_config(path: str | Path) -> DataConfig:
@@
 
 class DetokFilter(Filter):
@@
 
diff --git a/sfttrain/filters.py b/sfttrain/filters.py
@@
-from .records import Example
+from .records import Example
+from .tokenizer import LocalTokenizer
```