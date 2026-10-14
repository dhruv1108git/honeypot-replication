Subject: Fix missing alerts insertion and add alert severity handling

The nightly pipeline correctly records monitor results but never writes alert rows, causing alert‑related tests to fail. This patch updates `AlertSink.record` to also insert alert entries (including severity) for non‑none decisions, using the raw monitor score. It respects dry‑run mode and aligns with the updated alerts schema.

```diff
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index be2cda7..c3cbe3a 100644
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
+        Inserts a row into ``monitor_results`` (always) and, for any non‑none
+        decision, also inserts a row into ``alerts`` with a severity matching the decision.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Record the full monitor result.
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
+        # Record an alert row for any actionable decision.
+        if decision != "none":
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    result.agent_model,
+                    result.raw_score,        # integer score for alerts
+                    result.rationale,
+                    decision,
+                    decision,                # severity mirrors the decision
+                    now,
+                ),
+            )
+        # If a pager is configured, trigger it for page‑level alerts.
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
```