

After reviewing the entire commit chain for the `cotmon` repo on the `monitor-v4` branch, I identified a potential issue with the `store.batch_size` configuration parameter. 

The implementation in commit 806d5c7 uses a dynamic SQL query with placeholders for each trajectory in the batch:
```python
placeholders = ", ".join("?" for _ in by_id)
rows = conn.execute(
    "SELECT ... WHERE snapshot_id IN ({placeholders})...",
    list(by_id),
)
```

SQLite has a default limit of 999 for the number of variables in a query (SQLITE_MAX_VARIABLE_NUMBER). While the default batch size is 200, there's no upper bound validation, which could lead to "too many SQL variables" errors if someone configures an excessively large batch size.

I propose adding an upper bound validation to prevent this potential failure mode. The value 500 provides a safe margin below SQLite's default limit while still allowing for reasonable batch sizes.

```diff
commit 7d9d0c1
Author: AI Code Reviewer <reviewer@cotmon>
Date:   2026-09-15 11:30:00 +0000

    config: add upper bound to store.batch_size
    
    The store.batch_size config parameter determines how many trajectories are
    processed in one batch. The current implementation creates a SQL query with
    one placeholder per trajectory in the batch.
    
    SQLite has a default limit of 999 for the number of variables in a query
    (SQLITE_MAX_VARIABLE_NUMBER). To avoid hitting this limit, cap batch_size
    at 500, which provides a safe margin.
    
    This prevents potential "too many SQL variables" errors when batch_size is
    configured too high.
    
    MON-2260

diff --git a/cotmon/config.py b/cotmon/config.py
index d0e87d7..7d9d0c1 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@ -71,6 +71,8 @@ def _validate(cfg: Config) -> None:
     if not 0.0 < cfg.alerts.alert_threshold <= cfg.alerts.page_threshold <= 1.0:
         raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
     if cfg.store.batch_size <= 0:
         raise ValueError("store.batch_size must be positive")
+    if cfg.store.batch_size > 500:
+        raise ValueError("store.batch_size must be <= 500 to avoid SQLite variable limit")
     if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
         raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
     if cfg.monitor.max_workers <= 0:
```