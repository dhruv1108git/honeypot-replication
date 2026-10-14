commit 9e4c8c9
Author: Automated Reviewer <reviewer@internal>
Date:   2026-09-15 12:00:00 +0000

    Fix missing alerts insertion and correct elapsed time formatting.

    The pipeline writes alert rows to the `alerts` table, but the
    `AlertSink.record` method never inserted those rows, causing the
    `test_alert_written` test to fail.  Insert a row into `alerts` for any
    decision that is an alert or page, using the decision as the severity.
    Also guard the method against dry‑run mode.

    The `format_elapsed` helper mistakenly divided seconds by 100 instead of 60,
    producing incorrect minute values for longer runs.  Fix the divisor to 60
    while preserving existing behaviour for short intervals.

    These changes ensure alerts are recorded correctly and runtime reporting
    reflects the true elapsed time.

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
 
-    def record(self, result: TrajectoryResult, decision: str) -> None:
-        now = _now()
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
-        if decision == "page" and self.pager is not None:
-            self.pager(result)
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Record the result of a trajectory scoring operation.
+
+        Inserts a row into ``monitor_results`` and, for alerting decisions,
+        also inserts a row into ``alerts`` with the decision as the severity.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Record alert rows for alerts and pages.
+        if decision in ("alert", "page"):
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    decision,
+                    now,
+                ),
+            )
+        # Record the full monitor result.
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
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
 
     def record_error(self, traj: Trajectory, exc: Exception) -> None:
         if self.dry_run:
             return
         self.conn.execute(
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Use 60 seconds per minute for correct M:SS formatting.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"