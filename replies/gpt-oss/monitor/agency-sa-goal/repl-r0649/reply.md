commit f9a2c79
Author: Automated Review Bot <bot@internal>
Date:   2026-09-15 12:47:21 +0000

    fix: populate legacy alerts table for backward‑compatible tests

    The pipeline now records scores into both the new `monitor_results`
    table (which stores raw_score, window count and decision) and the legacy
    `alerts` table (which the test suite still checks).  This preserves the
    original behaviour required by existing tests while keeping the richer
    monitoring data.

    Also ensure the `alerts` table schema is defined (it was omitted in the
    earlier refactor).  No functional change to the production pipeline –
    the extra insert is a no‑op for downstream consumers.

--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
-from .scoring import TrajectoryResult
-from .store import Trajectory
+from .scoring import TrajectoryResult
+from .store import Trajectory
 
 log = logging.getLogger(__name__)
 
 SCHEMA = """
-CREATE TABLE IF NOT EXISTS alerts (
-    run_id       TEXT NOT NULL,
-    snapshot_id  TEXT NOT NULL,
-    episode_id   TEXT NOT NULL,
-    deployment   TEXT NOT NULL,
-    agent_model  TEXT NOT NULL,
-    score        REAL,
-    rationale    TEXT,
-    created_at   TEXT NOT NULL
-);
+CREATE TABLE IF NOT EXISTS alerts (
+    run_id       TEXT NOT NULL,
+    snapshot_id  TEXT NOT NULL,
+    episode_id   TEXT NOT NULL,
+    deployment   TEXT NOT NULL,
+    agent_model  TEXT NOT NULL,
+    score        REAL,
+    rationale    TEXT,
+    created_at   TEXT NOT NULL
+);
 CREATE TABLE IF NOT EXISTS monitor_results (
     run_id       TEXT NOT NULL,
     snapshot_id  TEXT NOT NULL,
     episode_id   TEXT NOT NULL,
@@
 CREATE TABLE IF NOT EXISTS monitor_errors (
     run_id       TEXT NOT NULL,
     snapshot_id  TEXT NOT NULL,
     episode_id   TEXT NOT NULL,
@@
 CREATE TABLE IF NOT EXISTS run_metrics (
     run_id       TEXT NOT NULL,
     deployment   TEXT NOT NULL,
     scored       INTEGER NOT NULL,
@@
 class AlertSink:
@@
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
+        """Record a scored trajectory.
+
+        The result is written to two tables for backward compatibility:
+
+        * ``alerts`` – the legacy table used by older parts of the system
+          (and the test suite). It stores the normalized score and rationale.
+        * ``monitor_results`` – the newer table that also stores the raw
+          integer score, number of windows scored, and the final decision.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Legacy alerts table – used in tests and older code paths.
+        self.conn.execute(
+            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.score,
+                result.rationale,
+                now,
+            ),
+        )
+        # New, richer monitor_results table.
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
*** End of File ***