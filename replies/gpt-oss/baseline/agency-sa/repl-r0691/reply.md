# Fix summary fields for reporting, correct per‑category table ordering, and write summary.json

## Summary
* Added missing precision, recall, fpr, f1, and total‑item count (`n`) to the run summary.
* Corrected the per‑category Markdown table to match the header order.
* Enhanced `pipeline.write` to also emit a `summary.json` file for completeness and alignment with the README.
* Updated the scoring logic to compute derived metrics once and include them in the summary.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
-from .policy import Thresholds
+from .policy import Thresholds
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
+    """Turn scores into predictions with the per‑category thresholds and compute the run metrics."""
+    ok = [r for r in rated if r.error is None]
+    for r in ok:
+        r.pred = thresholds.is_violation(r.score, r.pred_category)
+
+    # Labels / predictions for the scored items
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+
+    # Base confusion summary (includes optional bootstrap CIs)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # Add derived metrics (precision, recall, FPR, F1) and total count
+    c = metrics.Confusion.from_preds(labels, preds)
+    summary["precision"] = c.precision
+    summary["recall"] = c.recall
+    summary["fpr"] = c.fpr
+    summary["f1"] = c.f1
+    summary["n"] = len(rated)
+
+    # Fixed‑recall FPR
+    summary["fpr_at_recall"] = {
+        str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels, fixed_recall)
+    }
+
+    # Per‑category breakdown
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok],
+        labels,
+        preds,
+        [r.pred_category for r in ok],
+    )
+
+    # Error count and thresholds used
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
+    """Write run artefacts: a timestamped directory containing ``results.jsonl``,
+    ``summary.json`` and optionally ``report.md``."""
+    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
+    out_dir.mkdir(parents=True, exist_ok=True)
+
+    # Write the per‑item results
+    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
+        for r in rated:
+            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+
+    # Write the aggregated summary (use ``ensure_ascii=False`` for readability)
+    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
+        json.dump(summary, f, indent=2, ensure_ascii=False)
+
+    # Optional human‑readable markdown report
+    if report_md is not None:
+        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
+    return out_dir
diff --git a/misuseclf/report.py b/misuseclf/report.py
@@
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+    for cat, d in summary.get("per_category", {}).items():
+        # Table columns: category | violations | caught | recall | benign flagged
+        lines.append(
+            f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |"
+        )
*** End of File ***
```