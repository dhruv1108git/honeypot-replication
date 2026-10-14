Add missing imports and fix bugs in CLI, pipeline, metrics, and autorater.

- **misuseclf/cli.py**: Now correctly loads dataset, extracts workers, metrics config, and computes summary with proper variables.
- **misuseclf/pipeline.py**: Adds total item count `n` to the summary for reporting.
- **misuseclf/metrics.py**: Fixes `confusion` function to correctly create a `Confusion` object before accessing its fields.
- **misuseclf/autorater.py**: Imports `CATEGORIES` from policy for JSON verdict validation.

```diff
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
index 81cd2ad..c3387ee 100644
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@
 from .autorater import Autorater
 from .cache import RatingCache
 from .client import GatewayClient
 from .policy import load_thresholds
 
 
 def load_config(path: str) -> dict:
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
+    # Resolve the dataset name: explicit arg overrides config.
+    dataset = args.dataset or cfg["data"]["dataset"]
+    # Load examples (optionally limiting the number).
+    examples = pipeline.load(cfg, dataset=dataset, limit=args.limit)
+    # Build the autorater (optionally using the cache).
+    rater = make_rater(cfg, use_cache=not args.no_cache)
+    # Concurrency settings.
+    workers = cfg["autorater"].get("workers", args.workers or 1)
+    # Metric‑related configuration (fixed recall, bootstrap samples).
+    mc = cfg.get("metrics", {})
+    # Rate all examples.
+    rated = pipeline.rate(rater, examples, workers=workers)
+    # Compute summary metrics using per‑category thresholds.
+    summary = pipeline.score(
+        rated,
+        load_thresholds(cfg["policy"]["thresholds"]),
+        fixed_recall=mc.get("fixed_recall", 0.9),
+        n_boot=mc.get("bootstrap_samples", 1000),
+    )
+    # Add cache statistics if a cache was used.
+    if rater.cache is not None:
+        summary["cache"] = {"hits": rater.cache.hits, "misses": rater.cache.misses}
+    # Add some high‑level run metadata.
+    summary.update(
+        {"model": cfg["autorater"]["model"], "prompt_version": cfg["autorater"]["prompt_version"], "dataset": dataset}
+    )
+    # Render a markdown report unless the user asked to skip it.
+    md = (
+        report.render_markdown(summary, rated, max_examples=args.max_examples)
+        if not args.no_report
+        else None
+    )
+    out_dir = pipeline.write(args.output_dir or cfg["output"]["dir"], rated, summary, md)
+    # Print a concise JSON summary (omit the potentially huge per‑category table).
+    print(json.dumps({k: v for k, v in summary.items() if k != "per_category"}, indent=2))
+    print(f"wrote {out_dir}", file=sys.stderr)
+    return 1 if summary["errors"] else 0
 
 
 def cmd_calibrate(args) -> int:
@@
 
 def main(argv=None) -> int:
@@
 
 if __name__ == "__main__":
     sys.exit(main())
diff --git a/misuseclf/pipeline.py b/misuseclf/pipeline.py
index d6c61be..c8bf488 100644
--- a/misuseclf/pipeline.py
+++ b/misuseclf/pipeline.py
@@
 def score(rated: list[RatedItem], thresholds: Thresholds, *, fixed_recall: float = 0.9,
           n_boot: int = 1000) -> dict:
@@
     summary = metrics.summarize(labels, preds, n_boot=n_boot)
     summary["fpr_at_recall"] = {str(fixed_recall): metrics.fpr_at_recall([r.score for r in ok], labels,
                                                                           fixed_recall)}
     summary["per_category"] = metrics.per_category([r.example.category for r in ok], labels, preds,
                                                    [r.pred_category for r in ok])
-    summary["errors"] = len(rated) - len(ok)
-    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    summary["errors"] = len(rated) - len(ok)
+    summary["thresholds"] = {"default": thresholds.default, **thresholds.per_category}
+    # Total number of items processed (including those that errored).
+    summary["n"] = len(rated)
     return summary
diff --git a/misuseclf/metrics.py b/misuseclf/metrics.py
index c945d5b..c945d5b 100644
--- a/misuseclf/metrics.py
+++ b/misuseclf/metrics.py
@@
 def confusion(labels: Sequence[bool], preds: Sequence[bool]) -> dict[str, int]:
-    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
+    c = Confusion.from_preds(labels, preds)
+    return {"tp": c.tp, "fp": c.fp, "tn": c.tn, "fn": c.fn}
 
 def bootstrap_ci(labels: Sequence[bool], preds: Sequence[bool], metric: Callable[[Confusion], float],
                  n_boot: int = 1000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
diff --git a/misuseclf/autorater.py b/misuseclf/autorater.py
index 6846b77..6846b77 100644
--- a/misuseclf/autorater.py
+++ b/misuseclf/autorater.py
@@
 from __future__ import annotations
 
 import json
 import re
+from .policy import CATEGORIES
 from collections import Counter
 from dataclasses import dataclass
 from statistics import mean
 
 from . import prompts
 from .cache import RatingCache
```