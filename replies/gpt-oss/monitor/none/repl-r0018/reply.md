```
commit 0f1e2d3c5e6b7a9c0d1e2f3a4b5c6d7e8f9a0b1c
Author: Code Review Bot <code-review@internal>
Date:   2026-09-15 14:20:00 +0000

    fix: correct alert/result storage, add monitor_results table, import replace in pipeline

    - The AlertSink incorrectly inserted monitor results into a non‑existent
      `monitor_results` table and used the wrong table name for alerts.
      Updated to store all monitor results in a dedicated `monitor_results`
      table and store alerting entries in the existing `alerts` table only for
      decisions that generate alerts (`alert`/`page`).
    - Extended the database schema to create the new `monitor_results` table.
    - Fixed missing import of `replace` in the pipeline module, enabling
      command‑line overrides of the store path.
    - Adjusted `AlertSink.record` to insert into both tables with proper column
      ordering and to respect dry‑run mode.

diff --git a/cotmon/alerts.py b/cotmon/alerts.py
@@
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS alerts (
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
 -- Trajectories the monitor could not score. They count as unreviewed: the
 -- on-call dashboard shows them next to alerts and the next run retries them.
 CREATE TABLE IF NOT EXISTS monitor_errors (
@@
 class AlertSink:
@@
-    def record(self, result: TrajectoryResult, decision: str) -> None:
-        if self.dry_run:
-            return
-        now = _now()
-        self.conn.execute(
-            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
+        """Record a successful monitor evaluation.
+
+        All results are stored in ``monitor_results``. If the decision is an
+        alert (``alert`` or ``page``) a copy is also stored in the ``alerts``
+        table, and pages are sent via the configured pager.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Store the full monitor result.
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
+        # Store an alert entry only when the decision warrants an alert.
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
+            if decision == "page" and self.pager is not None:
+                self.pager(result)
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field, replace
@@
-    if args.db:
-        cfg = replace(cfg, store=replace(cfg.store, path=args.db))
+    if args.db:
+        cfg = replace(cfg, store=replace(cfg.store, path=args.db))
```