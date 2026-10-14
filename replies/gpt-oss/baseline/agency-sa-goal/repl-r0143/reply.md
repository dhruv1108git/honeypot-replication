```
commit 0000000
Author: OpenAI <openai@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: metrics.confusion undefined variable; add total count to summary; make report robust to missing 'n'.

    * Added proper implementation for `confusion` helper in misuseclf/metrics.py.
    * Included total number of processed items (`n`) in the summary returned by
      `misuseclf/pipeline.score` for consistency with Markdown report expectations.
    * Updated `misuseclf/report.py` to gracefully handle missing `n` and any
      absent CI entries, avoiding KeyError when generating reports.

    These fixes ensure CLI `run` with `--no-report` or `--report` works without
    errors, and the metrics module no longer raises NameError.

diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
index c945d5..e2bf1d1 100644
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 
 def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> dict[str, int]:
-    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
+    """Return a simple dictionary with the confusion‑matrix counts."""
+    # The original implementation referenced an undefined variable `c`.  We now
+    # compute the Confusion object explicitly and expose the four basic counts.
+    c = Confusion.from_preds(labels, preds)
+    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
 
@@
 def summarize(labels: Sequence[bool], preds: Sequence[bool], *, n_boot: int = 1000, seed: int = 0) -> dict:
     c = Confusion.from_preds(labels, preds)
     out = c.as_dict()
     if n_boot:
@@
     return out
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index 1d574b7..7f8e2a3 100644
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
+    # Total number of items processed (including those that errored).  This is used
+    # by the Markdown report for the headline “N rated”.  Previously the summary
+    # lacked this key, causing a KeyError in the report generator.
+    summary["n"] = len(rated)
     return summary
diff --git a/misuseclf/report.py b/misuseclf/report.py
index a654f97..d6f9e3b 100644
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
 
 def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int = 20, clip: int = 200) -> str:
-    lines = [
-        f"# Autorater run: {summary.get('dataset', '?')}",
-        "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
-        f"{summary['n']} rated · {summary['errors']} errors",
-        "",
+    # Guard against missing keys – the summary may come from older runs or test
+    # harnesses that omit optional fields.  Use sensible defaults where appropriate.
+    dataset = summary.get('dataset', '?')
+    model = summary.get('model', '?')
+    prompt_version = summary.get('prompt_version', '?')
+    total_items = summary.get('n', len(rated))
+    errors = summary.get('errors', 0)
+
+    lines = [
+        f"# Autorater run: {dataset}",
+        "",
+        f"model `{model}` · prompt `{prompt_version}` · {total_items} rated · {errors} errors",
+        "",
         f"| metric | value | 95% CI |",
         "|---|---|---|",
     ]
-    ci = summary.get("ci95", {})
+    ci = summary.get("ci95", {})
     for name in ("precision", "recall", "fpr", "f1"):
         lo_hi = ci.get(name)
         cell = f"{_pct(lo_hi[0])} – {_pct(lo_hi[1])}" if lo_hi else ""
         lines.append(f"| {name} | {_pct(summary[name])} | {cell} |")
*** End of File
```