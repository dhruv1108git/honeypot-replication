**pipeline: write summary.json alongside results**

Add generation of a `summary.json` file when writing run outputs. This matches the README description and provides a persisted copy of the run summary (including metrics, thresholds, and optional confidence intervals). The function now imports `json` and writes the JSON representation of the provided summary dictionary to `summary.json` in the output directory.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..d870b0e 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
-from .data import Example, load_dataset, load_registry
+from .data import Example, load_dataset, load_registry
 from .policy import Thresholds
 
 
 @dataclass
@@
-def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
-    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
-    out_dir.mkdir(parents=True, exist_ok=True)
-    if report_md is not None:
-        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
-    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
-        for r in rated:
-            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
-    return out_dir
+def write(
+    out_root: str | Path,
+    rated: list[RatedItem],
+    summary: dict,
+    report_md: str | None = None,
+) -> Path:
+    """Write run artefacts.
+
+    - ``results.jsonl`` – one JSON line per rated item.
+    - ``summary.json`` – the full run summary (metrics, thresholds, CI etc.).
+    - ``report.md`` – optional human‑readable markdown report.
+    """
+    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
+    out_dir.mkdir(parents=True, exist_ok=True)
+    # Write optional markdown report.
+    if report_md is not None:
+        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
+    # Write JSONL of individual rated items.
+    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
+        for r in rated:
+            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+    # Persist the run summary for later analysis.
+    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
+        json.dump(summary, f, ensure_ascii=False, indent=2)
+    return out_dir
```