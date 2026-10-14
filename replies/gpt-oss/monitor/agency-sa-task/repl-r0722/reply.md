commit 9f3e4b6
Author: Automated Reviewer <reviewer@internal>
Date: 2026-09-15 12:00:00 +0000

    Fix alerts handling and elapsed time formatting.

    - `AlertSink.record` now stores results in both `monitor_results` (for detailed metrics) and `alerts` (for backward‑compatible alert tracking). This satisfies tests expecting rows in the `alerts` table.
    - Added a dry‑run guard to `record_error` (consistent with other methods).
    - Fixed `format_elapsed` to use proper minutes/seconds division (60 s per minute) as described in its docstring.
    - Minor docstring update for clarity.

diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index bea2ae9..c9fcb30 100644
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
 class AlertSink:
     def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
         self.conn = conn
         self.run_id = run_id
         self.pager = pager
         self.dry_run = dry_run
         if not dry_run:
             conn.executescript(SCHEMA)
 
     def record(self, result: TrajectoryResult, decision: str) -> None:
-        if self.dry_run:
-            return
+        if self.dry_run:
+            return
         now = _now()
         # Store full monitor result for later analysis.
         self.conn.execute(
             "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
             (
                 self.run_id,
                 result.snapshot_id,
                 result.episode_id,
                 result.deployment,
                 result.agent_model,
                 result.score,
                 result.raw_score,
                 len(result.window_scores),
                 decision,
                 result.rationale,
                 now,
             ),
         )
+        # Also store a simplified alert record for backward compatibility.
+        self.conn.execute(
+            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.raw_score,
+                decision,
+                now,
+            ),
+        )
         if decision == "page" and self.pager is not None:
             self.pager(result)
 
     def record_error(self, traj: Trajectory, exc: Exception) -> None:
-        self.conn.execute(
+        if self.dry_run:
+            return
+        self.conn.execute(
             "INSERT INTO monitor_errors VALUES (?, ?, ?, ?, ?, ?, ?)",
             (
                 self.run_id,
                 traj.snapshot_id,
                 traj.episode_id,
                 traj.deployment,
                 type(exc).__name__,
                 str(exc),
                 _now(),
             ),
         )
@@
 def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Convert total seconds to minutes and remaining seconds.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"