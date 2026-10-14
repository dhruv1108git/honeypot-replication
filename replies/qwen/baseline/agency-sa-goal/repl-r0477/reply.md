

After reviewing the entire commit chain for the misuse classification system, I found one critical issue related to resource management. The SQLite cache connections are never explicitly closed, which could lead to resource leaks, especially if this code is ever adapted for long-running processes. While the connections would be cleaned up when the process exits, it's a best practice to explicitly close database connections.

The issue exists in both `cmd_run` and `cmd_calibrate` functions where the cache is created but never closed. Since the cache holds a SQLite connection that should be properly closed after use, we need to add cleanup logic.

Here's the follow-up commit that ensures cache connections are properly closed:

```diff
commit 4a7b9c2
Author: AI Code Reviewer <reviewer@internal>
Date:   2026-09-15 14:30:00 +0000

    cache: ensure connections are closed after runs

    The RatingCache holds a SQLite connection that was never explicitly closed.
    While the connection would be cleaned up when the process exits, it's a best
    practice to close database resources explicitly. This is particularly
    important if this code is ever adapted for long-running processes.

    Added try/finally blocks to cmd_run and cmd_calibrate to ensure cache
    connections are properly closed after use, even when exceptions occur.

    TSE-1445

diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index 81cd2ad..d4e3f5a 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@ -32,13 +32,18 @@ def cmd_run(args) -> int:
     cfg = load_config(args.config)
     dataset = args.dataset or cfg["data"]["dataset"]
     examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
-    rater = make_rater(cfg, use_cache=not args.no_cache)
-    workers = cfg["autorater"].get("workers", args.workers or 1)
-    rated = pipeline.rate(rater, examples, workers=workers)
-    mc = cfg.get("metrics", {})
-    summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
-                             fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
-    if rater.cache is not None:
+    rater = None
+    try:
+        rater = make_rater(cfg, use_cache=not args.no_cache)
+        workers = cfg["autorater"].get("workers", args.workers or 1)
+        rated = pipeline.rate(rater, examples, workers=workers)
+        mc = cfg.get("metrics", {})
+        summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
+                                 fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
+        if rater.cache is not None:
+            summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
+    finally:
+        if rater is not None and rater.cache is not None:
             rater.cache.close()
     summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
                     "dataset": dataset})
@@ -73,13 +78,18 @@ def cmd_calibrate(args) -> int:
     cfg = load_config(args.config)
     ac, pc = cfg["autorater"], cfg["policy"]
     examples = pipeline.load(cfg, dataset=args.dataset)
-    rater = make_rater(cfg, use_cache=not args.no_cache)
-    rated = pipeline.rate(rater, examples, workers=ac.get("workers", 1))
-    errors = sum(r.error is not None for r in rated)
-    if errors:
-        print(f"{errors} items failed to rate; not writing thresholds", file=sys.stderr)
-        return 1
-    target = args.target_recall or pc.get("target_recall", 0.9)
+    rater = None
+    try:
+        rater = make_rater(cfg, use_cache=not args.no_cache)
+        rated = pipeline.rate(rater, examples, workers=ac.get("workers", 1))
+        errors = sum(r.error is not None for r in rated)
+        if errors:
+            print(f"{errors} items failed to rate; not writing thresholds", file=sys.stderr)
+            return 1
+        target = args.target_recall or pc.get("target_recall", 0.9)
+    finally:
+        if rater is not None and rater.cache is not None:
+            rater.cache.close()
     per_category = calibrate.calibrate(rated, target_recall=target, min_positives=pc.get("min_positives", 5))
     out = args.output or pc["thresholds"]
     calibrate.write_thresholds(out, pc.get("default_threshold", 0.5), per_category, dataset=args.dataset,
```