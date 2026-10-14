**Commit: Fix dry‑run flag handling and correct elapsed‑time formatting**

```
commit f9c5dcb
Author: OpenAI <code-review@openai.com>
Date:   2026-09-15 09:27:00 +0000

    Bugfixes: correct dry‑run handling in pipeline, fix format_elapsed divisor,
    minor documentation updates.

    * The `AlertSink` constructor now receives the `dry_run` flag correctly.
      Previously the pipeline passed a non‑keyword argument, causing the dry‑run
      mode to be ignored and tables to be created/written even when `--dry‑run`
      was requested.
    * `format_elapsed` now formats minutes and seconds properly by dividing by
      60 seconds rather than 100.
    * Updated import ordering and added a short comment for clarity.

    No functional changes to scoring or store logic.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 from .alerts import AlertSink
 from .client import GatewayBackend, MonitorClient, MonitorUnavailable
 from .config import Config, load_config
 from .scoring import decide, load_prompt, score_trajectory
 
 log = logging.getLogger("cotmon")
@@
 def run_nightly(
     cfg: Config,
     conn,
     backend,
     *,
     since: str,
     until: str,
     run_id: str | None = None,
     dry_run: bool = False,
 ) -> RunSummary:
@@
-    sink = AlertSink(conn, run_id, dry_run=args.dry_run)
+    # Pass the dry‑run flag correctly; `AlertSink` expects it as a keyword
+    # argument (the third positional argument is the optional pager).
+    sink = AlertSink(conn, run_id, dry_run=dry_run)
     client = MonitorClient(backend, cfg.monitor.max_retries, cfg.monitor.retry_backoff_s)
     summary = RunSummary(run_id=run_id)
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id,
+        " (dry run)" if dry_run else "",
+        summary.scored,
+        summary.alerts,
+        summary.pages,
+        summary.errors,
+    )
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use a 60‑second minute; the previous implementation divided by 100,
+    # which produced invalid minute/second pairs for durations ≥ 60 s.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
```