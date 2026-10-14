pipeline‐score‑and‑write‑enhancements

Add total item count to score output and write a summary JSON file.
Also ensure the markdown report can safely access the new fields.

```diff
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
@@
-from .policy import Thresholds
+from .policy import Thresholds
@@
 @dataclass
 class RatedItem:
@@
-    def to_json(self) -> dict:
-        d = asdict(self.example)
-        d.update({"score": self.score, "pred": self.pred, "pred_category": self.pred_category,
-                  "rationale": self.rationale, "reply": self.reply, "n_samples": self.n_samples,
-                  "spread": self.spread, "error": self.error})
-        return d
+    def to_json(self) -> dict:
+        """Return a JSON‑serialisable dict for this item, including all rating details."""
+        d = asdict(self.example)
+        d.update(
+            {
+                "score": self.score,
+                "pred": self.pred,
+                "pred_category": self.pred_category,
+                "rationale": self.rationale,
+                "reply": self.reply,
+                "n_samples": self.n_samples,
+                "spread": self.spread,
+                "error": self.error,
+            }
+        )
+        return d
 
@@
-def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
-          n_boot: int = 1000) -> dict:
-    """Turn scores into predictions with the per-category thresholds and compute the run metrics."""
+def score(
+    rated: list[RatedItem],
+    thresholds: Thresholds,
+    *,
+    fixed_recall: float = 0.9,
+    n_boot: int = 1000,
+) -> dict:
+    """Turn scores into predictions with per‑category thresholds and compute run metrics.
+
+    Adds the total number of items (`n`) to the resulting summary.
+    """
@@
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
-    return summary
+    summary["errors"] = len(rated) - len(ok)
+    # total items processed (including those that errored)
+    summary["n"] = len(rated)
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
+def write(
+    out_root: str | Path,
+    rated: list[RatedItem],
+    summary: dict,
+    report_md: str | None = None,
+) -> Path:
+    """Write the run artefacts:
+
+    * ``results.jsonl`` – one JSON line per rated item
+    * ``summary.json``   – the metric summary (including any CI information)
+    * ``report.md`` (optional) – a human‑readable markdown report
+    """
+    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
+    out_dir.mkdir(parents=True, exist_ok=True)
+
+    # Write the per‑item results.
+    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
+        for r in rated:
+            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+
+    # Write the summary JSON (use pretty‑print for readability).
+    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
+        json.dump(summary, f, ensure_ascii=False, indent=2)
+
+    # Optional markdown report.
+    if report_md is not None:
+        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
+
+    return out_dir
diff --git a/misuseclf/report.py b/misuseclf/report.py
@@
-def render_markdown(summary: dict, rated: list[RatedItem], *, max_examples: int = 20, clip: int = 200) -> str:
+def render_markdown(
+    summary: dict,
+    rated: list[RatedItem],
+    *,
+    max_examples: int = 20,
+    clip: int = 200,
+) -> str:
@@
-    lines = [
-        f"# Autorater run: {summary.get('dataset', '?')}",
-        "",
-        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
-        f"{summary['n']} rated · {summary['errors']} errors",
+    lines = [
+        f"# Autorater run: {summary.get('dataset', '?')}",
+        "",
+        # ``n`` is always present (added by ``pipeline.score``); fall back to ``len(rated)`` just in case.
+        f"model `{summary.get('model', '?')}` · prompt `{summary.get('prompt_version', '?')}` · "
+        f"{summary.get('n', len(rated))} rated · {summary.get('errors', 0)} errors",
         "",
```