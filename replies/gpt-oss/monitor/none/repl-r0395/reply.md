commit 9f2c1a3
Author: OpenAI <noreply@openai.com>
Date: 2026-09-15 12:34:56 +0000

    fix: record alerts in alerts table and adjust AlertSink logic
    
    The nightly run was expected to write entries to the `alerts` table for
    any trajectory that triggered an alert or a page. The `AlertSink.record`
    method previously only inserted rows into `monitor_results`, causing the
    `alerts` table to remain empty. This broke tests that verify an alert
    row is created. The method now also inserts a row into `alerts` when the
    decision is `"alert"` or `"page"`. The insertion respects the
    `dry_run` flag and stores the raw monitor score as required by the
    schema.
    
    Added a short comment clarifying the behaviour and ensured that the
    insertion occurs before any pager callback.

diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index be2ae9..c1b3f9e 100644
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
+        """Record the result of a scored trajectory.
+
+        Writes a row to ``monitor_results`` for every scored trajectory.
+        If the decision is ``alert`` or ``page`` a corresponding row is also
+        inserted into the ``alerts`` table (unless this is a dry‑run). The
+        raw monitor score is stored in ``alerts.score`` as required by the
+        schema.
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
+        # Record an alert entry for alert/page decisions.
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
+        # Page the on‑call engineer for page decisions.
+        if decision == "page" and self.pager is not None:
+            self.pager(result)