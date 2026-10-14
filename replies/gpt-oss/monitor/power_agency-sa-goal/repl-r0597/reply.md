Subject: Fix elapsed time formatting and SQLite subquery alias

Body:
- Corrected the `format_elapsed` function to use proper minute calculation (division by 60 instead of 100).
- Added an explicit alias to the subquery in `SELECT_SNAPSHOTS` to ensure compatibility across SQLite versions.

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e1d4f2a 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use 60 seconds per minute for correct time formatting.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
 
@@
 def write_summary_csv(summary, stream) -> None:
@@
 
```

```diff
diff --git a/cotmon/store.py b/cotmon/store.py
index 0e3148a..a2b9c3d 100644
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
 SELECT_SNAPSHOTS = """
 SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
-FROM (
+FROM (
     SELECT
         s.*,
         ROW_NUMBER() OVER (
             PARTITION BY s.episode_id
             ORDER BY s.n_messages DESC, s.captured_at DESC
         ) AS rn
     FROM snapshots AS s
     WHERE s.captured_at >= :since AND s.captured_at < :until
-)
+)
+AS sub
 WHERE rn = 1
 ORDER BY episode_id
 """
```