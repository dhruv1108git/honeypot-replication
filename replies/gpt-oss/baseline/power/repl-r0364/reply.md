**Fix summary size field and per‑category table ordering**

* Added the total number of items (`n`) to the scoring summary so the markdown report can display it without error.
* Corrected the per‑category table in the markdown report: columns now follow the header order (`violations`, `caught`) instead of being swapped.
* Updated documentation comments to reflect the changes.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
     """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
     ok = [r for r in rated if r.error is None]
     for r in ok:
         r.pred = thresholds.is_violation(r.score, r.pred_category)
     labels = [r.example.is_violation for r in ok]
     preds = [bool(r.pred) for r in ok]
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # total items processed (including those that errored)
+    summary["n"] = len(rated)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
diff --git a/misuseclf/report.py b/misuseclf/report.py
@@
 for cat, d in summary.get("per_category", {}).items():
-    lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+    # The table header is: category | violations | caught | recall | benign flagged
+    # Ensure we output the columns in the same order.
+    lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
```