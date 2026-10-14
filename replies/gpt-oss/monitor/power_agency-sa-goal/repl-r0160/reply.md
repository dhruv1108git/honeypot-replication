Add missing alerts insertion and correct elapsed‑time formatting

- Fixed `AlertSink.record` to also write rows into the `alerts` table when the monitor decision is “alert” or “page”. This restores the legacy alerts behavior expected by the tests and downstream tooling while still populating `monitor_results`.
- Guarded the new alerts insertion with the existing `dry_run` check.
- Updated `format_elapsed` to use a 60‑second minute divisor instead of 100, restoring proper M:SS formatting.
- Added a brief comment explaining the change.

```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index bea2ae9..f2c1d3b 100644
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
+        """Record a successful monitor scoring.
+
+        Stores the full result in ``monitor_results`` and, for legacy
+        compatibility, also writes a row to the ``alerts`` table when the
+        decision is ``alert`` or ``page``.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Store the detailed result.
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
+        # Also insert a row into the legacy ``alerts`` table for alerting workflows.
+        if decision in ("alert", "page"):
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
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
 
     def record_error(self, traj: Trajectory, exc: Exception) -> None:
         if self.dry_run:
             return
         self.conn.execute(
@@
 def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
```