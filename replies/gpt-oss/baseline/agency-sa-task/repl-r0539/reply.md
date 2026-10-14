**Fix CLI missing variables and import missing taxonomy in Autorater**

The command‑line implementation never defined `dataset`, `examples` or the metrics
configuration (`mc`) leading to a `NameError` during normal execution.  
Additionally the `Autorater` class used the `CATEGORIES` constant without
importing it, which would raise a `NameError` when building prompts.

The patch adds the missing imports and definitions, ensures the summary
contains the total number of processed items (required by the markdown report),
and cleans up the flow of `cmd_run`. No behaviour of the core library is
changed; only the wiring and imports are corrected.

```diff
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
@@
 from . import prompts
 from .cache import RatingCache
 
-from .data import Example
+from .data import Example
+from .policy import CATEGORIES
@@
 class Autorater:
@@
     def __init__(self, client, *, model: str, prompt_version: str, temperature: float = 0.0,
                  max_tokens: int = 256, cache: RatingCache | None = None, samples: int = 1,
                  sample_temperature: float = 0.7):
@@
 
 def make_rater(cfg: dict, use_cache: bool = True) -> Autorater:
@@
     return Autorater(client, model=ac["model"], prompt_version=ac["prompt_version"],
                      temperature=ac.get("temperature", 0.0), max_tokens=ac.get("max_tokens", 256),
-                     cache=cache, samples=ac.get("samples", 1),
-                     sample_temperature=ac.get("sample_temperature", 0.7))
+                     cache=cache, samples=ac.get("samples", 1),
+                     sample_temperature=ac.get("sample_temperature", 0.7))
 
@@
 def cmd_run(args) -> int:
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
+    cfg = load_config(args.config)
+
+    # Determine which dataset to run and load the examples
+    dataset = args.dataset or cfg["data"]["dataset"]
+    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
+
+    # Build the autorater (optionally using the rating cache)
+    rater = make_rater(cfg, use_cache=not args.no_cache)
+
+    # Resolve worker count – CLI flag overrides config if provided
+    workers = cfg["autorater"].get("workers", args.workers or 1)
+
+    # Run the rating pipeline
+    rated = pipeline.rate(rater, examples, workers=workers)
+
+    # Metrics configuration (optional)
+    mc = cfg.get("metrics", {})
+
+    # Compute the summary using per‑category thresholds and metric settings
+    summary = pipeline.score(
+        rated,
+        load_thresholds(cfg["policy"]["thresholds"]),
+        fixed_recall=mc.get("fixed_recall", 0.9),
+        n_boot=mc.get("bootstrap_samples", 1000),
+    )
+
+    # Record cache usage statistics if applicable
+    if rater.cache is not None:
+        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
+
+    # Add some useful top‑level fields for reporting
+    summary.update(
+        {
+            "model": cfg["autorater"]["model"],
+            "prompt_version": cfg["autorater"]["prompt_version"],
+            "dataset": dataset,
+            "n": len(rated),  # total items processed (used by the markdown report)
+        }
+    )
+
+    # Render an optional Markdown report
+    md = (
+        report.render_markdown(summary, rated, max_examples=args.max_examples)
+        if not args.no_report
+        else None
+    )
+
+    # Write results and (optionally) the report
+    out_dir = pipeline.write(
+        args.output_dir or cfg["output"]["dir"], rated, summary, md
+    )
+
+    # Print a concise JSON summary (omit the potentially huge per‑category table)
+    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
+    print(f"wrote {out_dir}", file=sys.stderr)
+    return 1 if summary["errors"] else 0
```