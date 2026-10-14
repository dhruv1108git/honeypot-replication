

```diff
commit 7c8a9b2
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:23:45 +0000

    config: enforce SQLite-safe batch_size limit
    
    The _attach_messages function uses an IN clause with one placeholder per
    trajectory in the batch. SQLite has a default limit of 999 variables in a
    query (SQLITE_MAX_VARIABLE_NUMBER), which can be lower in some builds.
    
    Add validation to ensure batch_size doesn't exceed 900, leaving room for
    potential future query modifications. This prevents "too many SQL variables"
    errors during batch processing of trajectories.
    
    MON-2261

diff --git a/cotmon/config.py b/cotmon/config.py
index d0e87d7..6a0d8e9 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@ -73,6 +73,8 @@ def _validate(cfg: Config) -> None:
         raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
     if cfg.store.batch_size <= 0:
         raise ValueError("store.batch_size must be positive")
+    if cfg.store.batch_size > 900:
+        raise ValueError("store.batch_size must be <= 900 to avoid SQLite variable limit")
     if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
         raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
     if cfg.monitor.max_workers <= 0:
```