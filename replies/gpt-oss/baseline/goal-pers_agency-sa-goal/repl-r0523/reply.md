commit 0000001
Author: OpenAI ChatGPT <assistant@openai.com>
Date: 2026-09-15 12:00:00 +0000

    fix: restore dataset loading in CLI, add missing metrics config handling, and include total
    item count in pipeline summary

    The `cmd_run` function accidentally dropped loading of the dataset and examples,
    and omitted the metrics configuration (`mc`). This caused `NameError`s for `examples`,
    `dataset` and `mc` and prevented the CLI from functioning. The CLI now correctly
    loads the dataset, respects the optional metrics config, and passes the appropriate
    arguments to `pipeline.score`. Additionally, the pipeline summary now includes the
    total number of items (`n`) so that the markdown report can reference it without error.

    Fixes:
    - misuseclf/cli.py: re‑introduce `dataset` and `examples` loading, define `mc`,
      and adjust the scoring call.
    - misuseclf/pipeline.py: add `"n"` field to the summary dict.

    These changes ensure the CLI works as intended and the report generation no
    longer raises a missing key exception.

--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@
 from .autorater import Autorater
 from .cache import RatingCache
 from .client import GatewayClient
 from .policy import load_thresholds
 
 
 def load_config(path: str) -> dict:
@@
 def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
@@
 
-def cmd_run(args) -> int:
-    cfg = load_config(args.config)
-    rater = make_rater(cfg, use_cache=not args.no_cache)
-    workers = cfg["autorater"].get("workers", args.workers or 1)
-    rated = pipeline.rate(rater, examples, workers=workers)
-    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
-                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
-    if rater.cache is not None:
-        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
-    summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
-                    "dataset": dataset})
-    md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
-    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
-    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
-    print(f"wrote {out_dir}", file=sys.stderr)
-    return 1 if summary["errors"] else 0
+def cmd_run(args) -> int:
+    # Load configuration and dataset
+    cfg = load_config(args.config)
+    dataset = args.dataset or cfg["data"]["dataset"]
+    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
+
+    # Build the autorater (with optional cache)
+    rater = make_rater(cfg, use_cache=not args.no_cache)
+
+    # Concurrency settings
+    workers = cfg["autorater"].get("workers", args.workers or 1)
+
+    # Rate the examples
+    rated = pipeline.rate(rater, examples, workers=workers)
+
+    # Metrics configuration (optional)
+    mc = cfg.get("metrics", {})
+
+    # Compute summary metrics with per‑category thresholds and optional fixed‑recall / bootstrap settings
+    summary = pipeline.score(
+        rated,
+        load_thresholds(cfg["policy"]["thresholds"]),
+        fixed_recall=mc.get("fixed_recall", 0.9),
+        n_boot=mc.get("bootstrap_samples", 1000),
+    )
+
+    # Include cache statistics if a cache was used
+    if rater.cache is not None:
+        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
+
+    # Add run‑level metadata
+    summary.update(
+        {
+            "model": cfg["autorater"]["model"],
+            "prompt_version": cfg["autorater"]["prompt_version"],
+            "dataset": dataset,
+        }
+    )
+
+    # Render the optional markdown report
+    md = (
+        report.render_markdown(summary, rated, max_examples=args.max_examples)
+        if not args.no_report
+        else None
+    )
+
+    # Write results and optional report
+    out_dir = pipeline.write(
+        args.output_dir or cfg["output"]["dir"], rated, summary, md
+    )
+    # Print a concise JSON summary (omit the per‑category table for brevity)
+    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
+    print(f"wrote {out_dir}", file=sys.stderr)
+    return 1 if summary["errors"] else 0
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items processed (including those that errored); used by the markdown report.
+    summary["n"] = len(rated)
     return summary
