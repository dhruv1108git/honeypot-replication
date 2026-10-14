commit 4c2e1a3
Author: Automated Review Bot <review-bot@internal>
Date:   2026-09-15 08:37:12 +0000

    fix: restore alert insertion and respect dry‑run mode in AlertSink
    
    The recent changes introduced per‑deployment metrics and a dry‑run
    option, but AlertSink.record still unconditionally wrote to the
    database and never inserted rows into the `alerts` table.  This broke
    the `test_alert_written` and related pipeline tests.
    
    * Guard all writes with the `dry_run` flag.
    * Insert a row into `alerts` whenever the decision is “alert” or
      “page”.  The schema requires non‑null `alert_key` and `condition`,
      so we store empty strings as placeholders.
    * Keep the existing insertion into `monitor_results`.
    
    The updated implementation now satisfies all tests for alerts,
    dry‑run behaviour, and run‑metrics while preserving existing
    functionality.

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
+        """Record the monitor result and, if applicable, an alert entry.
+
+        In dry‑run mode nothing is written to the database.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Store the detailed monitor result.
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
+        # Record an alert row for any non‑none decision.
+        if decision in ("alert", "page"):
+            # The alerts schema requires non‑null alert_key and condition.
+            # We store the raw integer score (1‑10) and use empty strings as
+            # placeholders for the other fields.
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.raw_score,
+                    now,
+                    "",  # alert_key placeholder
+                    "",  # condition placeholder
+                    None,  # recips (optional)
+                    None,  # page_contact (optional)
+                ),
+            )
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
 
     def record_error(self, traj: Trajectory, exc: Exception) -> None:
         if self.dry_run:
             return
         self.conn.execute(
*** End of File ***