**Fix pipeline output handling and add missing summary fields**

- `pipeline.score` now includes the total number of items (`n`) in the summary, which is required by the markdown report.
- `pipeline.write` returns the created output directory path, fixing the missing return value that broke downstream code and tests.
- `metrics.confusion` helper is corrected to properly compute confusion counts using the `Confusion` class, preventing a `NameError` if used elsewhere. 

These changes resolve failing tests around the pipeline write function and ensure the report generation works correctly.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
     """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
     ok = [r for r in rated if r.error is None]
     for r in ok:
         r.pred = thresholds.is_violation(r.score, r.pred_category)
-    labels = [r.example.is_violation for r in ok]
-    preds = [bool(r.pred) for r in ok]
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # total number of items processed (including those that errored)
+    summary["n"] = len(rated)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
@@
-def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
-    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
-    out_dir.mkdir(parents=True, exist_ok=True)
-    if report_md is not None:
-        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
-    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
-        for r in rated:
-            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
+    """Write results and optional markdown report to a timestamped directory.
+
+    Returns the path to the created output directory.
+    """
+    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
+    out_dir.mkdir(parents=True, exist_ok=True)
+    if report_md is not None:
+        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
+    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
+        for r in rated:
+            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+    return out_dir
```

```diff
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
@@
 def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> dict[str, int]:
-    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
+    """Return basic confusion counts without the derived metrics."""
+    c = Confusion.from_preds(labels, preds)
+    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
```