commit ffffffff
Author: OpenAI <openai@example.com>
Date: 2026-09-15 09:00:00 +0000

    fix: correct alerts insertion, per‑deployment alert rates, and elapsed time formatting
    
    * AlertSink.record now matches the `alerts` table schema (10 placeholders) and
      inserts columns in the correct order: run_id, snapshot_id, episode_id,
      deployment, agent_model, score, raw_score, decision, rationale, created_at.
    
    * AlertSink.record and AlertSink.record_error short‑circuit on dry‑run correctly.
    
    * DeploymentStats.alert_rate is now computed per‑deployment as alerts / scored
      (instead of alerts / total scored) in RunSummary.finalise.
    
    * format_elapsed now divides by 60 seconds to produce proper M:SS output.
    
    * Added a small inline comment explaining the minute conversion.

--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
 class AlertSink:
@@
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
-                decision,
-                result.rationale,
-                now,
-            ),
-        )
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Write the monitor result and, if it crossed a threshold, an alert row."""
+        if self.dry_run:
+            return
+        now = _now()
+        # Full monitor result, including raw score and window count.
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
+        # Alerts table has 10 columns: run_id, snapshot_id, episode_id,
+        # deployment, agent_model, score, raw_score, decision, rationale, created_at.
+        self.conn.execute(
+            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                result.snapshot_id,
+                result.episode_id,
+                result.deployment,
+                result.agent_model,
+                result.score,
+                result.raw_score,
+                decision,
+                result.rationale,
+                now,
+            ),
+        )
         if decision == "page" and self.pager is not None:
             self.pager(result)
@@ class AlertSink:
         self.conn.execute(
             "INSERT INTO monitor_errors VALUES (?, ?, ?, ?, ?, ?, ?)",
@@
 class RunSummary:
@@
     pages: int = 0
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
@@
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Compute per‑deployment alert rates (alerts / scored)."""
+        for stats in self.per_deployment.values():
+            stats.alert_rate = (
+                stats.alerts / stats.scored if stats.scored else 0.0
+            )
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(seconds: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
+    # ``divmod`` by 60 yields proper minute/second values.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
*** End of File ***