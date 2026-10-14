commit ffffff1
Author: Automated Refactor <refactor@internal>
Date: 2026-09-15 12:00:00 +0000

    Fix configuration validation and elapsed time formatting.

    * Remove stale validation of `transcript.max_transcript_chars`, a field
      that no longer exists after migrating to window‑based transcript
      handling. The old check caused an `AttributeError` during config
      loading, preventing the application and tests from starting.
    * Correct `format_elapsed` to compute minutes and seconds using a
      divisor of 60 instead of 100, yielding proper “M:SS” output for
      durations longer than a minute.

--- a/cotmon/config.py
+++ b/cotmon/config.py
@@
 def _validate(cfg: Config) -> None:
@@
     if not 0.0 < cfg.alerts.alert_threshold <= cfg.alerts.page_threshold <= 1.0:
         raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
     if cfg.store.batch_size <= 0:
         raise ValueError("store.batch_size must be positive")
-    if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
-        raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
-    if cfg.monitor.max_workers <= 0:
-        raise ValueError("monitor.max_workers must be positive")
-    if cfg.transcript.max_transcript_chars < 1000:
-        raise ValueError("transcript.max_transcript_chars is too small")
+    if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
+        raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
+    if cfg.monitor.max_workers <= 0:
+        raise ValueError("monitor.max_workers must be positive")
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
*** End of File ***