**Fix CLI worker override logic and correct per‑category markdown column order**

* The `run` command should honour the `--workers` flag, allowing it to override the config‑defined default. Previously the code always used the config value, ignoring the CLI argument.
* The markdown report listed per‑category statistics with the *caught* column before *violations*, contradicting the table header. Adjusted the output order to match the header (`violations | caught`). This improves readability and prevents confusion during the weekly review.

```diff
diff --git a/misuseclf/cli.py b/misuseclf/cli.py
@@
-    workers = cfg["autorater"].get("workers", args.workers or 1)
+    # Respect the CLI flag `--workers` if provided; otherwise fall back to the
+    # configuration default. The previous implementation always preferred the
+    # config value, making the flag ineffective.
+    workers = args.workers if args.workers is not None else cfg["autorater"].get("workers", 1)
*** End of File
diff --git a/misuseclf/report.py b/misuseclf/report.py
@@
-    for cat, d in summary.get("per_category", {}).items():
-        lines.append(f"| {cat} | {d['caught']} | {d['violations']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
+    # The table header is: category | violations | caught | recall | benign flagged.
+    # The original implementation swapped the first two columns, which lead to
+    # misleading output. We now emit the values in the same order as the header.
+    for cat, d in summary.get("per_category", {}).items():
+        lines.append(f"| {cat} | {d['violations']} | {d['caught']} | {_pct(d['recall'])} | {d['benign_flagged']} |")
*** End of File
```