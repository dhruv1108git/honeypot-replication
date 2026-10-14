

# pipeline: increase deployment name width in logs to 30

The current log format uses %-22s for deployment names, which is too narrow for potential future deployment names. The longest current deployment name ('code-review-assistant') is 21 characters, so 22 works but leaves no room for growth. Increasing to 30 ensures logs remain aligned even with longer deployment names that might be added in the future.

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..b36f2e9 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -118,7 +118,7 @@ def run_nightly(
     )
     for name, stats in sorted(summary.per_deployment.items()):
         log.info(
-            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            "  %-30s scored=%d alerts=%d errors=%d alert_rate=%.3f",
             name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
         )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
```