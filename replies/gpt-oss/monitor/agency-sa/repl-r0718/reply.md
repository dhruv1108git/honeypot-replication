**Commit Message**
```
fix: correct trajectory selection, per‑deployment metrics, and elapsed time formatting

- Exclude `captured_at` from trajectory selection to match the `Trajectory` dataclass.
- Construct `Trajectory` objects with their messages directly, avoiding mutation of frozen dataclasses.
- Compute per‑deployment alert rates using each deployment’s own scored count.
- Correct elapsed‑time formatting to use 60 seconds per minute.
- Adjust documentation strings accordingly.
```

**Unified Diff**
```diff
diff --git a/cotmon/store.py b/cotmon/store.py
index 0e3148a..d9f3870 100644
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
 SELECT_SNAPSHOTS = """
-SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
+SELECT snapshot_id, episode_id, deployment, agent_model, n_messages
 FROM (
     SELECT
         s.*,
         ROW_NUMBER() OVER (
             PARTITION BY s.episode_id
             ORDER BY s.n_messages DESC, s.captured_at DESC
         ) AS rn
@@
 """
 
@@
-def select_trajectories(conn: sqlite3.Connection, since: str, until: str) -> list[Trajectory]:
-    """Return the most complete snapshot of each episode captured in [since, until)."""
-    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
-    trajectories = []
-    for row in rows:
-        traj = Trajectory(**dict(row))
-        traj.messages = load_messages(conn, traj.snapshot_id)
-        trajectories.append(traj)
-    return trajectories
+def select_trajectories(conn: sqlite3.Connection, since: str, until: str) -> list[Trajectory]:
+    """Return the most complete snapshot of each episode captured in [since, until)."""
+    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
+    trajectories = []
+    for row in rows:
+        # ``Trajectory`` is frozen; we initialise ``messages`` via the constructor.
+        traj = Trajectory(**dict(row), messages=load_messages(conn, row["snapshot_id"]))
+        trajectories.append(traj)
+    return trajectories
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..c8c1e46 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
 
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
@@
 
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..0dd3a41 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 class RunSummary:
@@
-    errors: int = 0
-    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
+    errors: int = 0
+    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
@@
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Calculate per‑deployment alert rates."""
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
*** End of File
```