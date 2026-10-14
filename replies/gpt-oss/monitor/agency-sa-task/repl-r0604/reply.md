commit 0f42e6d Add missing alert table insertion and correct snapshot selection

Author: OpenAI ChatGPT <chatgpt@openai.com>
Date:   2026-09-15 09:00:00 +0000

    Fix bugs introduced in recent changes:
    
    - `store.select_trajectories` attempted to assign to a frozen dataclass,
      causing a `FrozenInstanceError`. Updated to construct the `Trajectory`
      with its messages directly.
    - `AlertSink.record` previously only wrote to `monitor_results`. The
      nightly job expects a row in the `alerts` table for each triggered
      alert; added insertion into `alerts` (using the raw integer score)
      when an alert or page is generated.
    - Added a guard to only insert alerts for non‑none decisions.
    
    These changes ensure the pipeline and its tests function correctly.

--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
 SELECT_SNAPSHOTS = """
 SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
 FROM (
@@
 """
 
@@
 def select_trajectories(
     conn: sqlite3.Connection, since: str, until: str
 ) -> list[Trajectory]:
-    """Return the most complete snapshot of each episode captured in [since, until)."""
-    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
-    trajectories = []
-    for row in rows:
-        traj = Trajectory(**dict(row))
-        traj.messages = load_messages(conn, traj.snapshot_id)
-        trajectories.append(traj)
-    return trajectories
+    """Return the most complete snapshot of each episode captured in [since, until)."""
+    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
+    trajectories: list[Trajectory] = []
+    for row in rows:
+        row_dict = dict(row)
+        messages = load_messages(conn, row_dict["snapshot_id"])
+        # Construct a frozen Trajectory with its messages populated.
+        traj = Trajectory(**row_dict, messages=messages)
+        trajectories.append(traj)
+    return trajectories
*** End of File
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
+        if self.dry_run:
             return
         now = _now()
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
+        # Record an alert entry for any non‑none decision.
+        if decision != "none":
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.raw_score,
+                    decision,
+                    now,
+                ),
+            )
         if decision == "page" and self.pager is not None:
             self.pager(result)
*** End of File