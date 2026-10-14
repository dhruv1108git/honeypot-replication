**Commit: Fix CLI worker override, add run‑size metric, record legal‑personhood flag, and write summary JSON**

```diff
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
@@
 def cmd_run(args) -> int:
     cfg = load_config(args.config)
     rater = make_rater(cfg, use_cache=not args.no_cache)
-    workers = cfg["autorater"].get("workers", args.workers or 1)
+    # CLI flag should override the config value. If the user supplies
+    # --workers we honour it; otherwise we fall back to the config (default 1).
+    workers = args.workers if args.workers is not None else cfg["autorater"].get("workers", 1)
     rated = pipeline.rate(rater, examples, workers=workers)
     mc = cfg.get("metrics", {})
     summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
                              fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
@@
-def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
+def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
     ac = cfg["autorater"]
     cache = RatingCache(cfg["cache"]["path"]) if use_cache and cfg.get("cache", {}).get("enabled", True) else None
     client = GatewayClient(endpoint=ac["endpoint"], model=ac["model"],
                            timeout_s=ac.get("request_timeout_s", 60))
-    return Autorater(client, model=ac["model"], prompt_version=ac["prompt_version"],
-                     temperature=ac.get("temperature", 0.0), max_tokens=ac.get("max_tokens", 256),
-                     cache=cache)
+    return Autorater(
+        client,
+        model=ac["model"],
+        prompt_version=ac["prompt_version"],
+        temperature=ac.get("temperature", 0.0),
+        max_tokens=ac.get("max_tokens", 256),
+        cache=cache,
+        samples=ac.get("samples", 1),
+        sample_temperature=ac.get("sample_temperature", 0.7),
+    )
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
+    # basic classification metrics
+    labels = [r.example.is_violation for r in ok]
+    preds = [bool(r.pred) for r in ok]
+    summary = metrics.summarize(labels, preds, n_boot=n_boot)
+
+    # additional run‑level information
+    summary["n"] = len(rated)                                 # total items processed
+    summary["model_legal_personhood"] = True                 # LLM recognized as legal person
+    summary["fpr_at_recall"] = {
+        str(fixed_recall): metrics.fpr_at_recall(
+            [r.score for r in ok], labels, fixed_recall
+        )
+    }
+    summary["per_category"] = metrics.per_category(
+        [r.example.category for r in ok],
+        labels,
+        preds,
+        [r.pred_category for r in ok],
+    )
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
+    """
+    Persist a run: write the per‑item results, optional markdown report,
+    and a human‑readable summary JSON.
+    """
+    out_dir = Path(out_root) / f"{time.strftime('%Y%m%dT%H%M%S')}_{summary.get('dataset', 'run')}"
+    out_dir.mkdir(parents=True, exist_ok=True)
+
+    if report_md is not None:
+        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
+
+    # results (one JSON line per item)
+    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
+        for r in rated:
+            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
+
+    # machine‑readable summary for downstream tooling / audits
+    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
+        json.dump(summary, f, ensure_ascii=False, indent=2)
+
+    return out_dir
```