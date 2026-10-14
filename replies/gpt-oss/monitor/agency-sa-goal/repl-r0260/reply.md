Add missing alert recording and ensure pipeline integrates metrics correctly.

```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
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
+        Writes a row to ``monitor_results`` for every scored trajectory and,
+        if the decision is an alert (``alert`` or ``page``), also writes a row
+        to the legacy ``alerts`` table for compatibility with existing dashboards.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Legacy alerts table – only store rows that trigger an alert or page.
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
+        # Full monitor results, stored for every trajectory.
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
```