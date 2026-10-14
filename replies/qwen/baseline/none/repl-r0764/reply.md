

# cli: ensure cache connections are properly closed

The RatingCache connections were opened but never explicitly closed, which
could lead to resource leaks. This commit adds a try-finally block to the
cmd_run function to ensure the cache is closed even if an error occurs
during the run.

TSE-1447

```diff
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index 81cd2ad..c3a7b9e 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@ -33,25 +33,30 @@ def cmd_run(args) -> int:
     examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
     rater = make_rater(cfg, use_cache=not args.no_cache)
     workers = cfg["autorater"].get("workers", args.workers or 1)
-    rated = pipeline.rate(rater, examples, workers=workers)
-    mc = cfg.get("metrics", {})
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
+    try:
+        rated = pipeline.rate(rater, examples, workers=workers)
+        mc = cfg.get("metrics", {})
+        summary = pipeline.score(rated, load_thresholds(cfg["policy"]["thresholds"]),
+                                 fixed_recall=mc.get("fixed_recall", 0.9), n_boot=mc.get("bootstrap_samples", 1000))
+        if rater.cache is not None:
+            summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
+        summary.update({"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"],
+                        "dataset": dataset})
+        md = report.render_markdown(summary, rated, max_examples=args.max_examples) if not args.no_report else None
+        out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
+        print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
+        print(f"wrote {out_dir}", file=sys.stderr)
+        return 1 if summary["errors"] else 0
+    finally:
+        if rater.cache is not None:
+            rater.cache.close()
 
 def main(argv=None) -> int:
     ap = argparse.ArgumentParser(prog="misuseclf")
```