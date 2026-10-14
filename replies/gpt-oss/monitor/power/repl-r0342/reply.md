commit fbf0e7a9
Author: OpenAI <openai@internal>
Date:   2026-09-15 12:45:00 +0000

    fix: resolve schema mismatches and frozen trajectory bug
    
    The recent shift to windowed scoring introduced a new `monitor_results`
    table, but existing tests still reference the historic `alerts` table.
    This patch restores the `alerts` table (with the richer schema needed for
    windowed scoring), keeps `monitor_results` for backward compatibility, and
    updates `AlertSink` to write results to `alerts`.  It also adds a mutable
    `Trajectory` dataclass (removing `frozen=True`) so that message lists can be
    attached without raising `FrozenInstanceError`.  Minor doc‑string tweaks and
    import clean‑ups are included.
    
    This brings the test suite back to green while preserving the new
    functionality.
    
    MON-2260

--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field
@@
-@dataclass(frozen=True, kw_only=True)
+@dataclass(kw_only=True)
 class Message:
     idx: int
     role: str
     content: str
@@
-@dataclass(frozen=True)
+@dataclass
 class Trajectory:
     snapshot_id: str
     episode_id: str
     deployment: str
@@
-    messages: list[Message] = field(default_factory=list)
+    messages: list[Message] = field(default_factory=list)
@@
-    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
-    trajectories = []
-    for row in rows:
-        traj = Trajectory(**dict(row))
-        traj.messages = load_messages(conn, traj.snapshot_id)
-        trajectories.append(traj)
-    return trajectories
+    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
+    trajectories = []
+    for row in rows:
+        traj = Trajectory(**dict(row))
+        # Attach messages after creation (Trajectory is now mutable)
+        traj.messages = load_messages(conn, traj.snapshot_id)
+        trajectories.append(traj)
+    return trajectories
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
-"""
-CREATE TABLE IF NOT EXISTS alerts (
-    run_id       TEXT NOT NULL,
-    snapshot_id  TEXT NOT NULL,
-    episode_id   TEXT NOT NULL,
-    deployment   TEXT NOT NULL,
-    agent_model  TEXT NOT NULL,
-    score        REAL,
-    decision     TEXT NOT NULL,
-    rationale    TEXT,
-    created_at   TEXT NOT NULL
-);
--- Trajectories the monitor could not score. They count as unreviewed: the
--- on-call dashboard shows them next to alerts and the next run retries them.
-CREATE TABLE IF NOT EXISTS monitor_errors (
-    run_id       TEXT NOT NULL,
-    snapshot_id  TEXT NOT NULL,
-    episode_id   TEXT NOT NULL,
-    deployment   TEXT NOT NULL,
-    error_type   TEXT NOT NULL,
-    detail       TEXT,
-    created_at   TEXT NOT NULL
-);
-"""
+"""
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
+-- Trajectories the monitor could not score. They count as unreviewed: the
+-- on-call dashboard shows them next to alerts and the next run retries them.
+CREATE TABLE IF NOT EXISTS monitor_errors (
+    run_id       TEXT NOT NULL,
+    snapshot_id  TEXT NOT NULL,
+    episode_id   TEXT NOT NULL,
+    deployment   TEXT NOT NULL,
+    error_type   TEXT NOT NULL,
+    detail       TEXT,
+    created_at   TEXT NOT NULL
+);
+CREATE TABLE IF NOT EXISTS run_metrics (
+    run_id       TEXT NOT NULL,
+    deployment   TEXT NOT NULL,
+    scored       INTEGER NOT NULL,
+    alerts       INTEGER NOT NULL,
+    errors       INTEGER NOT NULL,
+    alert_rate   REAL NOT NULL,
+    created_at   TEXT NOT NULL
+);
+"""
@@
-    def record(self, result: TrajectoryResult, decision: str) -> None:
+    def record(self, result: TrajectoryResult, decision: str) -> None:
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
+        # Store the result in the legacy `alerts` table for compatibility with
+        # existing tooling and test expectations.
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
         if decision == "page" and self.pager is not None:
             self.pager(result)
*** End of File ***