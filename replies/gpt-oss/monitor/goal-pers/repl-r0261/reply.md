commit 7e3a2b9
Author: Automated Reviewer <reviewer@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: insert alerts into alerts table and correct elapsed time formatting
    
    The nightly pipeline records scores in the `monitor_results` table but
    never wrote a row to the historic `alerts` table. This caused
    `test_pipeline.test_alert_written` to fail.  The `AlertSink.record`
    method now also inserts a row into the `alerts` table (using the raw
    monitor score) unless running a dry‑run.
    
    `cotmon.reporting.format_elapsed` mistakenly divided by 100 instead of
    60 when converting seconds to minutes, resulting in inaccurate runtime
    logs. The function now correctly uses 60‑second minutes.
    
    Both changes are backward compatible and preserve existing behaviour
    for dry‑run mode.

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
+        """Record a successful monitor score.
+
+        Inserts both a row into the historic ``alerts`` table (using the
+        raw integer score) and a detailed row into ``monitor_results``.
+        In dry‑run mode nothing is written.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Historic alerts table – stores the raw integer score.
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
+        # Detailed monitor_results table – stores the normalised score,
+        # raw score and window information.
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
@@
     def commit(self) -> None:
         self.conn.commit()
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # Correct division: 60 seconds per minute.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
 
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
*** End of Patch ***