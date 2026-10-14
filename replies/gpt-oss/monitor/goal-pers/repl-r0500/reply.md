commit f8c3d9f
Author: OpenAI <noreply@openai.com>
Date:   2026-09-15 12:45:00 +0000

    fix: route monitor results to both monitor_results and alerts tables

    The pipeline now inserts every scored trajectory into the `monitor_results`
    table (including raw score and window count) and additionally records an
    entry in the legacy `alerts` table only for trajectories that trigger an
    alert or a page. This satisfies the test suite expectations:
    
    - Successful alerts are present in the `alerts` table.
    - All scored results are stored in `monitor_results`.
    - Errors do not create `monitor_results` rows.
    
    The `alerts` schema already contains `raw_score` and `n_windows`, so the
    same values are inserted there. The `monitor_results` table is added to the
    schema (if missing) to avoid missing‑table errors.

--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS alerts (
     run_id TEXT NOT NULL,
     snapshot_id TEXT NOT NULL,
     episode_id TEXT NOT NULL,
     deployment TEXT NOT NULL,
     agent_model TEXT NOT NULL,
@@
     created_at TEXT NOT NULL
 );
 CREATE TABLE IF NOT EXISTS monitor_errors (
     run_id TEXT NOT NULL,
@@
     created_at TEXT NOT NULL
 );
+CREATE TABLE IF NOT EXISTS monitor_results (
+    run_id       TEXT NOT NULL,
+    snapshot_id  TEXT NOT NULL,
+    episode_id   TEXT NOT NULL,
+    deployment   TEXT NOT NULL,
+    agent_model  TEXT NOT NULL,
+    score        REAL NOT NULL,
+    raw_score    INTEGER NOT NULL,
+    n_windows    INTEGER NOT NULL,
+    decision     TEXT NOT NULL,
+    rationale    TEXT,
+    created_at   TEXT NOT NULL
+);
 CREATE TABLE IF NOT EXISTS run_metrics (
     run_id       TEXT NOT NULL,
     deployment   TEXT NOT NULL,
     scored       INTEGER NOT NULL,
@@
 class AlertSink:
@@
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
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Record a scored trajectory.
+
+        All results are stored in ``monitor_results``. If the decision is
+        ``alert`` or ``page`` an additional row is inserted into the legacy
+        ``alerts`` table for backward‑compatible alert handling.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Insert the full result into monitor_results.
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
+        # Insert into alerts only for actual alerts/pages.
+        if decision in ("alert", "page"):
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.score,
+                    result.raw_score,
+                    len(result.window_scores),
+                    decision,
+                    result.rationale,
+                    now,
+                ),
+            )
*** End of File ***