fix: add missing 'n' to summary and correct per‑category report column order

The markdown report expects a total‑item count (`summary['n']`) which was never set,
causing a KeyError when generating reports.  Additionally the per‑category table
displayed values in the wrong order (caught vs. violations), which made the
report confusing and inconsistent with its header.

The changes:
- `pipeline.score` now records the total number of items as `summary["n"]`.
- `report.render_markdown` now prints the per‑category rows in the order
  specified by the header: violations, caught, recall, benign flagged.

These fixes ensure the CLI can generate a valid `report.md` and that the
per‑category breakdown matches its column titles.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..1d574b7 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # total number of items processed (including errors); needed by the markdown report
+    summary["n"] = len(rated)
     return summary
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..a654f97 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        # match the header order: violations first, then caught
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
 
     ok = [r for r in rated if r.error is None]
     fps = [r for r in ok if r.pred and not r.example.is_violation]
     fns = [r for r in ok if not r.pred and r.example.is_violation]
```