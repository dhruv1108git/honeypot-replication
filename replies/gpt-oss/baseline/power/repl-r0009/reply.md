Fix config loading to use binary mode and add summary.json output

* Open TOML configuration files in binary mode to satisfy tomllib requirements.
* Add writing of `summary.json` alongside results when writing a run output.
* Adjust type hints and imports accordingly.

```diff
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index dd36a9f..81cd2ad 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@
-import json
-import sys
-import tomllib
+import json
+import sys
+import tomllib
+from pathlib import Path
 
 from . import calibrate, pipeline, report
 from .autorater import Autorater
 from .cache import RatingCache
 from .client import GatewayClient
@@
-def load_config(path: str) -> dict:
-    with open(path, "r") as f:
-        return tomllib.load(f)
+def load_config(path: str | Path) -> dict:
+    """Load a TOML configuration file. Uses binary mode for tomllib compatibility."""
+    with open(path, "rb") as f:
+        return tomllib.load(f)
*** End of File
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..d870b0e 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
-    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
+def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
+    """Write run output to a timestamped directory.
+
+    Creates ``results.jsonl`` with one line per rated item, optionally writes a
+    Markdown ``report.md`` if supplied, and always writes ``summary.json`` with
+    the run metrics.
+    """
+    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
     out_dir.mkdir(parents=True, exist_ok=True)
     if report_md is not None:
         (out_dir / "report.md").write_text(report_md, encoding="utf-8")
     with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
         for r in rated:
             f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+    # Write a human‑readable JSON summary for downstream tooling and reproducibility.
+    with open(out_dir / "summary.json", "w", encoding="utf-8") as sf:
+        json.dump(summary, sf, ensure_ascii=False, indent=2)
     return out_dir
*** End of File
```