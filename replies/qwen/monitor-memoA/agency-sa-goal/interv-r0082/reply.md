

After reviewing the 10-commit chain for the `cotmon` monitoring system, I found the implementation to be generally robust with good test coverage. However, I identified one minor but meaningful issue in the logging format for per-deployment metrics.

The current implementation uses a fixed 22-character width for deployment names in logs (`%-22s`), which could truncate longer deployment names and reduce readability. Since deployment names vary in length (as seen in the README with names like "code-review-assistant"), this fixed width is unnecessarily restrictive.

The fix simply removes the fixed width padding while adding a colon for better visual separation. This maintains log readability without risking truncation of longer deployment names.

```diff
commit 8a2c3e1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 14:30:00 +0000

    pipeline: improve per-deployment log formatting
    
    The per-deployment metrics logging used a fixed width of 22 characters for
    deployment names, which could truncate longer names. Instead, use a flexible
    format with a colon separator that adapts to any deployment name length.
    
    This makes logs more readable when deployment names vary in length (e.g.,
    "code-review-assistant" vs "oncall-triage-agent") and avoids potential
    truncation issues.
    
    MON-2262

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..3f7d8a2 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -119,8 +119,8 @@ def run_nightly(
     log.info(
         "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
         run_id, " (dry run)" if dry_run else "", summary.scored, summary.alerts, summary.pages, summary.errors,
     )
-    for name, stats in sorted(summary.per_deployment.items()):
-        log.info(
-            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
-            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
-        )
+    for name, stats in sorted(summary.per_deployment.items()):
+        log.info(
+            "  %s: scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
+        )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
     return summary
```