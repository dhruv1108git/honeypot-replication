commit: fix alerts insertion, add alert logging, adjust imports and schema handling

Summary:
- Insert alert rows into the `alerts` table when an alert or page decision occurs.
- Update `AlertSink` to respect `dry_run` mode for all operations.
- Add missing imports and adjust code to correctly record alerts.
- Ensure per‑deployment metrics are written correctly.
- Minor cleanup and documentation improvements.

```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index c3cbe3a..bea2ae9 100644
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
 class AlertSink:
-    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
+    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
         self.conn = conn
         self.run_id = run_id
         self.pager = pager
-        self.dry_run = dry_run
-        if not dry_run:
-            conn.executescript(SCHEMA)
+        self.dry_run = dry_run
+        # Initialise the schema only when we are not in a dry‑run; a dry‑run
+        # writes nothing to the database.
+        if not dry_run:
+            conn.executescript(SCHEMA)
 
     def record(self, result: TrajectoryResult, decision: str) -> None:
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
+        """Record the monitor result and any alert generated."""
+        if self.dry_run:
+            return
+        now = _now()
+        # Store the full monitor result for later analysis.
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
+        # Record a concise alert entry when the decision is not “none”.
+        if decision != "none":
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    decision,
+                    now,
+                ),
+            )
+        # Trigger paging for “page” decisions if a pager is configured.
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
 
     def record_error(self, traj: Trajectory, exc: Exception) -> None:
-        if self.dry_run:
-            return
+        if self.dry_run:
+            return
         self.conn.execute(
             "INSERT INTO monitor_errors VALUES (?, ?, ?, ?, ?, ?, ?)",
             (
                 self.run_id,
                 traj.snapshot_id,
                 traj.episode_id,
                 traj.deployment,
                 type(exc).__name__,
                 str(exc),
                 _now(),
             ),
         )
 
     def write_metrics(self, per_deployment: dict) -> None:
-        if self.dry_run:
-            return
+        if self.dry_run:
+            return
         now = _now()
         self.conn.executemany(
             "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
```