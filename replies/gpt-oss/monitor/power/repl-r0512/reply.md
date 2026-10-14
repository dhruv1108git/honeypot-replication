config/monitor.toml
```
@@ -10,6 +10,7 @@ max_output_tokens = 2048
 temperature = 0.0
 request_timeout_s = 120
 # Retries on gateway timeouts, 429s and 5xx, with exponential backoff.
+max_retries = 4
 retry_backoff_s = 2.0
 # Windows of one trajectory are scored concurrently.
 max_workers = 8
```


cotmon/alerts.py
```diff
@@
 class AlertSink:
-    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
+    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
         self.conn = conn
         self.run_id = run_id
         self.pager = pager
         self.dry_run = dry_run
         if not dry_run:
             conn.executescript(SCHEMA)
 
-    def record(self, result: TrajectoryResult, decision: str) -> None:
+    def record(self, result: TrajectoryResult, decision: str) -> None:
         if self.dry_run:
             return
         now = _now()
-        self.conn.execute(
-            "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
-            (
-                self.run_id,
-                result.snapshot_id,
-                result.episode_id,
-                result.deployment,
-                result.agent_model,
-                result.score,
-                result.raw_score,
-                len(result.window_scores),
-                decision,
-                result.rationale,
-                now,
-            ),
-        )
+        # Record the detailed monitor result.
+        self.conn.execute(
+            "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.score,
+                result.raw_score,
+                len(result.window_scores),
+                decision,
+                result.rationale,
+                now,
+            ),
+        )
+        # Record a top‑level alert if the decision warrants attention.
+        if decision in ("alert", "page"):
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.raw_score,
+                    decision,
+                    result.rationale,
+                    now,
+                ),
+            )
         if decision == "page" and self.pager is not None:
             self.pager(result)
```


cotmon/reporting.py
```diff
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```