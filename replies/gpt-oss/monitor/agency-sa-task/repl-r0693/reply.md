commit 9c1a2e3
Author: OpenAI ChatGPT <noreply@openai.com>
Date:   2026-09-15 12:00:00 +0000

    fix: add missing alerts table and record alerts alongside monitor_results

    The refactor that introduced `monitor_results` renamed the original alerts
    table but the test suite (and existing deployments) still expect an
    `alerts` table to exist and to contain one row per scored trajectory.
    This commit restores the `alerts` table (with the same schema as
    `monitor_results`) and makes `AlertSink.record` insert into both tables.
    The change is safe for dry‑run mode (no schema is created) and preserves
    the existing `monitor_results` table for backward compatibility.

    MON-2260

--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS monitor_results (
     run_id       TEXT NOT NULL,
     snapshot_id  TEXT NOT NULL,
     episode_id   TEXT NOT NULL,
     deployment   TEXT NOT NULL,
     agent_model  TEXT NOT NULL,
-    score        REAL NOT NULL,
-    raw_score    INTEGER NOT NULL,
-    n_windows    INTEGER NOT NULL,
+    score        REAL NOT NULL,
+    raw_score    INTEGER NOT NULL,
+    n_windows    INTEGER NOT NULL,
     decision     TEXT NOT NULL,
     rationale    TEXT,
     created_at   TEXT NOT NULL
 );
+CREATE TABLE IF NOT EXISTS alerts (
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
 CREATE INDEX IF NOT EXISTS monitor_results_by_run ON monitor_results (run_id);
 CREATE INDEX IF NOT EXISTS monitor_results_by_deployment ON monitor_results (deployment);
 CREATE INDEX IF NOT EXISTS monitor_results_by_snapshot ON monitor_results (snapshot_id);
 CREATE INDEX IF NOT EXISTS monitor_results_by_severity ON monitor_results (decision);
@@
 class AlertSink:
@@
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
+        # Insert into the primary monitor_results table.
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
+        # Also insert a duplicate row into the legacy alerts table for compatibility.
+        self.conn.execute(
+            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
@@
         if decision == "page" and self.pager is not None:
             self.pager(result)
 
*** End of File
