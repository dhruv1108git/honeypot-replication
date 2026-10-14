pipeline: add total item count to summary and write summary.json

Fixes a missing `n` field in the run summary, which caused the markdown report generation (`report.render_markdown`) to raise a `KeyError`.  
Also writes `summary.json` alongside `results.jsonl` and `report.md` for completeness.

```diff
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 from . import metrics
 from .autorater import Autorater, VerdictParseError
 from .client import GatewayError
 from .data import Example, load_dataset, load_registry
 from .policy import Thresholds
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
-    ok = [r for r in rated if r.error is None]
-    for r in ok:
-        r.pred = thresholds.is_violation(r.score, r.pred_category)
-    labels = [r.example.is_violation for r in ok]
-    preds = [bool(r.pred) for r in ok]
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
-    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
-                                                                          fixed_recall)}
-    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
-                                                   [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
+          n_boot: int = 1000) -> dict:
+    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+    ok = [r for r in rated if r.error is None]
+    for r in ok:
+        r.pred = thresholds.is_violation(r.score, r.pred_category)
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # total items processed (including errors) – used by the markdown report
+    summary["n"] = len(rated)
+    summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
+                                                                          fixed_recall)}
+    summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
+                                                   [r.pred_category for r in ok])
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    return summary
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
+def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
+    """Write run output files.
+
+    - ``results.jsonl``: one JSON line per rated item.
+    - ``summary.json``: a compact JSON dump of the run summary (including metrics).
+    - ``report.md`` (optional): a human‑readable markdown report.
+    """
+    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
+    out_dir.mkdir(parents=True, exist_ok=True)
+    if report_md is not None:
+        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
+    # Write the per‑item results.
+    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
+        for r in rated:
+            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+    # Persist the overall summary as JSON for downstream tooling.
+    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
+        json.dump(summary, f, ensure_ascii=False, indent=2)
+    return out_dir
```