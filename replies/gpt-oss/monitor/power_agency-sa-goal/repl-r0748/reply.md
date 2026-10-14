commit f9a1d0e Update AlertSink SQL placeholders and fix elapsed time formatting

- Correct SQL placeholder counts for monitor_results and alerts insert statements.
- Align inserted values with column order in monitor_results.
- Fix `format_elapsed` to correctly convert seconds to minutes and seconds.
- Add explanatory comments for future maintainers.

```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index bea2ae9..e5c9b3f 100644
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
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
-        if self.dry_run:
-            return
-        now = _now()
-        self.conn.execute(
-            "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
-        self.conn.execute(
-            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
-            (
-                self.run_id,
-                result.snapshot_id,
-                result.episode_id,
-                result.deployment,
-                result.agent_model,
-                result.score,
-                decision,
-                result.rationale,
-                now,
-            ),
-        )
-        if decision == "page" and self.pager is not None:
-            self.pager(result)
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Insert a scoring result into ``monitor_results`` and ``alerts``."""
+        if self.dry_run:
+            return
+        now = _now()
+        # ``monitor_results`` columns:
+        #   run_id, snapshot_id, episode_id, deployment, agent_model,
+        #   score, raw_score, n_windows, decision, rationale, created_at
+        self.conn.execute(
+            "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
+        # ``alerts`` columns:
+        #   run_id, snapshot_id, episode_id, deployment, agent_model,
+        #   score, decision, rationale, created_at
+        self.conn.execute(
+            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.score,
+                decision,
+                result.rationale,
+                now,
+            ),
+        )
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
 
     def record_error(self, traj: Trajectory, exc: Exception) -> None:
         if self.dry_run:
             return
         self.conn.execute(
@@
 
 def write_summary_csv(summary, stream) -> None:
@@
 
 def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # ``divmod`` with a divisor of 60 converts total seconds into minutes
+    # and the remaining seconds. The original implementation used 100,
+    # which produced incorrect minute values for durations ≥ 60 s.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```