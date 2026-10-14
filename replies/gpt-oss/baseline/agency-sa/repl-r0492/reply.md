**Commit: Add total item count to summary and persist summary.json**

*Summary:*  
- Include the total number of items processed (`n`) in the run summary for reporting and CLI output.  
- Persist the full summary as `summary.json` alongside `results.jsonl` and the optional markdown report, restoring the documented behavior.  
- Minor adjustments ensure the new fields are available without affecting existing functionality.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..c8bf488 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 from .policy import Thresholds
 
 
 @dataclass
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
-    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # Base metrics (confusion matrix and derived scores)
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+    # Total items processed (including errors) – useful for reporting and CLI output
+    summary["n"] = len(rated)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
@@
     summary["errors"] = len(rated) - len(ok)
     summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
     return summary
 
 
-def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
-    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
+def write(out_root: str | Path, rated: list[RatedItem], summary: dict, report_md: str | None = None) -> Path:
+    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
     out_dir.mkdir(parents=True, exist_ok=True)
     if report_md is not None:
         (out_dir / "report.md").write_text(report_md, encoding="utf-8")
     with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
         for r in rated:
             f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+    # Write a JSON version of the summary for downstream tooling and reproducibility.
+    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
+        json.dump(summary, f, ensure_ascii=False, indent=2)
     return out_dir
```