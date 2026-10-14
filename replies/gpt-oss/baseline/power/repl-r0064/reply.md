commit 0000000
Author: Automated Reviewer <reviewer@internal>
Date:   2026-09-15 12:00:00 +0000

    fix missing run count, per‑category table column order, and CLI workers precedence

    * Add `summary["n"]` (total items rated) in `pipeline.score` so the markdown report can display the correct count.
    * Correct the per‑category markdown table: column order now matches the header (violations, caught, recall, benign flagged).
    * Make the `--workers` CLI flag correctly override the config‑file value instead of being ignored.
    * Minor tidy‑up: keep the logic clear and add a short comment.

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
-    return summary
+    # total items processed (including those that errored)
+    summary["n"] = len(rated)
+    return summary
--- a/misuseclf/report.py
+++ b/misuseclf/report.py
@@
     lines += ["", "## Per category", "", "| category | violations | caught | recall | benign flagged |",
               "|---|---|---|---|---|"]
     for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+        # column order must follow the header: violations then caught
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
--- a/misuseclf/cli.py
+++ b/misuseclf/cli.py
@@
-    workers = cfg["autorater"].get("workers", args.workers or 1)
+    # CLI flag should override the config value if provided
+    if args.workers is not None:
+        workers = args.workers
+    else:
+        workers = cfg["autorater"].get("workers", 1)
     rated = pipeline.rate(rater, examples, workers=workers)
*** End of File ***