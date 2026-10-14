commit 9f0c7e9
Author: OpenAI Code Review Bot <code-review@example.com>
Date: 2026-09-15 12:34:56 +0000

    fix: correct alert insertion, per‑deployment alert rate, and elapsed time formatting
    
    - AlertSink.record now inserts the correct number of columns into the `alerts`
      table (the schema only has eight columns). The previous implementation
      attempted to insert a rationale column that does not exist, causing a
      runtime SQLite error.
    - RunSummary.finalise now calculates each deployment's alert rate based on
      its own scored count rather than the global total, fixing an inaccurate
      metric.
    - format_elapsed now splits seconds into minutes and seconds using 60,
      matching the documented M:SS format.
    
    These fixes ensure that the nightly job runs without SQL errors,
    produces correct per‑deployment metrics, and logs proper elapsed time.

```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
@@
 class AlertSink:
     def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
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
-        if decision in ("alert", "page"):
-            self.conn.execute(
-                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
-                (
-                    self.run_id,
-                    result.snapshot_id,
-                    result.episode_id,
-                    result.deployment,
-                    result.agent_model,
-                    result.score,
-                    decision,
-                    result.rationale,
-                    now,
-                ),
-            )
-            if decision == "page" and self.pager is not None:
-                self.pager(result)
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Record a successful monitor evaluation.
+
+        Inserts the detailed result into ``monitor_results`` and, for
+        alerts/pages, writes a summary row to ``alerts``. No entry is made
+        when running in ``dry‑run`` mode.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Full result, including raw score and per‑window data.
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
+        # Alerts table has only eight columns; rationale is stored only in
+        # ``monitor_results``.
+        if decision in ("alert", "page"):
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.score,
+                    decision,
+                    now,
+                ),
+            )
+            if decision == "page" and self.pager is not None:
+                self.pager(result)
 
     def record_error(self, traj: Trajectory, exc: Exception) -> None:
         if self.dry_run:
             return
         self.conn.execute(
@@
 class RunSummary:
@@
     errors: int = 0
-    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
+    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
@@
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        # Compute alert rate per deployment, using that deployment's own
+        # scored count (avoids dividing by the global total).
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
+    # Convert seconds → minutes + remaining seconds.
+    minutes, remainder = divmod(int(seconds), 60)
     return f"{minutes}:{remainder:02d}"
```