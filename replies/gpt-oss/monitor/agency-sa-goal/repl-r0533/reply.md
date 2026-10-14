Commit: Fix pipeline missing imports, add day_bounds, ensure alerts are recorded, and correct message loading

--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 from . import store
 from .reporting import format_elapsed, write_summary_csv
 from .alerts import AlertSink
-from .client import GatewayBackend, MonitorClient, MonitorUnavailable
+from .client import GatewayBackend, MonitorClient, MonitorUnavailable
 from .config import Config, load_config
-from .scoring import decide, load_prompt, score_trajectory
+from .scoring import decide, load_prompt, score_trajectory
+from .parse import MonitorParseError
@@
 log = logging.getLogger("cotmon")
@@
 class RunSummary:
@@
     pages: int = 0
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
@@
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
@@
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
             stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
+def day_bounds(date_str: str) -> tuple[str, str]:
+    """Return ISO‑8601 UTC bounds for the given YYYY‑MM‑DD date string.
+
+    The lower bound is the start of the day (00:00:00Z) and the upper bound
+    is the start of the next day.
+    """
+    d = date.fromisoformat(date_str)
+    since = f"{d.isoformat()}T00:00:00Z"
+    until = f"{(d + timedelta(days=1)).isoformat()}T00:00:00Z"
+    return since, until
@@
 def run_nightly(
@@
     summary = RunSummary(run_id=run_id)
     batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
     for batch in batches:
         for traj in batch:
@@
                 sink.record_error(traj, exc)
                 summary.errors += 1
                 stats.errors += 1
                 continue
@@
     summary.finalise()
     sink.write_metrics(summary.per_deployment)
     sink.commit()
@@
 def main(argv: list[str] | None = None) -> int:
@@
-    since, until = day_bounds(args.date)
+    since, until = day_bounds(args.date)
@@
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
 class AlertSink:
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
+        """Record the result of scoring a trajectory.
+
+        Stores the raw monitor result, and also records an alert entry when the
+        decision is ``alert`` or ``page``. In dry‑run mode nothing is written.
+        """
+        if self.dry_run:
+            return
+        now = _now()
+        # Record an alert when the monitor says to alert or page.
+        if decision != "none":
+            # severity mirrors the decision name.
+            severity = decision
+            self.conn.execute(
+                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?)",
+                (
+                    self.run_id,
+                    result.snapshot_id,
+                    result.episode_id,
+                    result.deployment,
+                    severity,
+                    now,
+                ),
+            )
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
+        if decision == "page" and self.pager is not None:
+            self.pager(result)
*** End of File
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
 SELECT_MESSAGES = """
-SELECT snapshot_id, idx, role, content, reasoning, reasoning_summary
+SELECT idx, role, content, reasoning, reasoning_summary
 FROM messages
 WHERE snapshot_id = ?
 ORDER BY idx
 """
*** End of File