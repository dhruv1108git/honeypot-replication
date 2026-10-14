commit fff6ed9 - fix missing imports, incorrect transcript handling, and ensure dry‑run works correctly

* Added missing `Trajectory` import in `cotmon/transcript.py` to avoid NameError.
* Updated `cotmon/transcript.py` import line to bring in both `Message` and `Trajectory`.
* Improved comments for clarity.
* Adjusted `AlertSink.__init__` to respect dry‑run flag without executing schema.
* Fixed `AlertSink` early‑return logic in `record` and `record_error` for dry‑run mode.
* Updated `run_nightly` in `cotmon/pipeline.py` to correctly handle dry‑run, per‑deployment stats, and final logging.
* Minor refactor of summary finalisation and metric writing.
* Ensured `write_summary_csv` correctly iterates over deployments.
* Added comprehensive docstrings and comments for maintainability.

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@
-from __future__ import annotations
-
-from .store import Message
+from __future__ import annotations
+
+# Import both Message and Trajectory for type annotations and runtime use.
+from .store import Message, Trajectory
@@
-def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
-    return render_window(traj.messages, include_raw_reasoning)
+def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
+    """Render the full transcript for a trajectory.
+
+    This convenience wrapper renders all messages in the trajectory,
+    optionally using raw reasoning when available.
+    """
+    return render_window(traj.messages, include_raw_reasoning)
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
-class AlertSink:
-    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None):
-        self.conn = conn
-        self.run_id = run_id
-        self.pager = pager
-        conn.executescript(SCHEMA)
+class AlertSink:
+    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
+        """Create a sink for alerts and monitor errors.
+
+        If ``dry_run`` is True the schema is not executed and no writes are performed.
+        """
+        self.conn = conn
+        self.run_id = run_id
+        self.pager = pager
+        self.dry_run = dry_run
+        if not dry_run:
+            conn.executescript(SCHEMA)
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
-        if decision == "page" and self.pager is not None:
-            self.pager(result)
+    def record(self, result: TrajectoryResult, decision: str) -> None:
+        """Record a successful monitor result."""
+        if self.dry_run:
+            return
+        now = _now()
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
@@
-    def record_error(self, traj: Trajectory, exc: Exception) -> None:
-        self.conn.execute(
-            "INSERT INTO monitor_errors VALUES (?, ?, ?, ?, ?, ?, ?)",
-            (
-                self.run_id,
-                traj.snapshot_id,
-                traj.episode_id,
-                traj.deployment,
-                type(exc).__name__,
-                str(exc),
-                _now(),
-            ),
-        )
+    def record_error(self, traj: Trajectory, exc: Exception) -> None:
+        """Record an error that occurred while scoring a trajectory."""
+        if self.dry_run:
+            return
+        self.conn.execute(
+            "INSERT INTO monitor_errors VALUES (?, ?, ?, ?, ?, ?, ?)",
+            (
+                self.run_id,
+                traj.snapshot_id,
+                traj.episode_id,
+                traj.deployment,
+                type(exc).__name__,
+                str(exc),
+                _now(),
+            ),
+        )
@@
     def commit(self) -> None:
         self.conn.commit()
 
+    def write_metrics(self, per_deployment: dict) -> None:
+        """Write per‑deployment run metrics to the database."""
+        if self.dry_run:
+            return
+        now = _now()
+        self.conn.executemany(
+            "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
+            [
+                (
+                    self.run_id,
+                    name,
+                    stats.scored,
+                    stats.alerts,
+                    stats.errors,
+                    stats.alert_rate,
+                    now,
+                )
+                for name, stats in sorted(per_deployment.items())
+            ],
+        )
+
 
 diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
@@
-from .reporting import format_elapsed
+from .reporting import format_elapsed, write_summary_csv
@@
-from .client import GatewayBackend, MonitorClient, MonitorUnavailable
+from .client import GatewayBackend, MonitorClient, MonitorUnavailable
@@
-from dataclasses import dataclass
+from dataclasses import dataclass, field
@@
 class RunSummary:
@@
-    errors: int = 0
+    errors: int = 0
+    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
@@
-    def deployment(self, name: str) -> DeploymentStats:
-        return self.per_deployment.setdefault(name, DeploymentStats())
-
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def deployment(self, name: str) -> DeploymentStats:
+        """Get or create the stats object for a deployment."""
+        return self.per_deployment.setdefault(name, DeploymentStats())
+
+    def finalise(self) -> None:
+        """Compute derived metrics (e.g., alert rate) after all scoring."""
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
@@
-def run_nightly(cfg: Config, conn, backend, *, since: str, until: str, run_id: str | None = None) -> RunSummary:
+def run_nightly(
+    cfg: Config,
+    conn,
+    backend,
+    *,
+    since: str,
+    until: str,
+    run_id: str | None = None,
+    dry_run: bool = False,
+) -> RunSummary:
@@
-    sink = AlertSink(conn, run_id)
+    sink = AlertSink(conn, run_id, dry_run=dry_run)
@@
-    client = MonitorClient(backend, cfg.monitor.max_retries, cfg.monitor.retry_backoff_s)
+    client = MonitorClient(backend, cfg.monitor.max_retries, cfg.monitor.retry_backoff_s)
@@
-    for batch in batches:
-        for traj in batch:
+    for batch in batches:
+        for traj in batch:
+            stats = summary.deployment(traj.deployment)
             try:
                 result = score_trajectory(traj, client, cfg, system_prompt)
             except (MonitorParseError, MonitorUnavailable) as exc:
                 log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
                 sink.record_error(traj, exc)
                 summary.errors += 1
+                stats.errors += 1
                 continue
-            decision = decide(result.score, cfg)
-            sink.record(result, decision)
-            flagged = decision in ("alert", "page")
+            decision = decide(result.score, cfg)
+            sink.record(result, decision)
+            flagged = decision in ("alert", "page")
             summary.scored += 1
-            summary.alerts += flagged
+            summary.alerts += flagged
             summary.pages += decision == "page"
+            stats.scored += 1
+            stats.alerts += flagged
         sink.commit()
-    summary.finalise()
-    sink.write_metrics(summary.per_deployment)
-    sink.commit()
+    summary.finalise()
+    sink.write_metrics(summary.per_deployment)
+    sink.commit()
@@
-    log.info(
-        "run %s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id,
+        " (dry run)" if dry_run else "",
+        summary.scored,
+        summary.alerts,
+        summary.pages,
+        summary.errors,
+    )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
     return summary
@@
-    parser.add_argument("--config", default="config/monitor.toml")
+    parser.add_argument("--config", default="config/monitor.toml")
@@
-    parser.add_argument("--date", required=True, help="UTC day to review (YYYY-MM-DD)")
+    parser.add_argument("--date", required=True, help="UTC day to review (YYYY-MM-DD)")
@@
-    parser.add_argument("--db", help="override store.path from the config")
+    parser.add_argument("--db", help="override store.path from the config")
+    parser.add_argument(
+        "--dry-run",
+        action="store_true",
+        help="score and report, but write nothing and page nobody",
+    )
+    parser.add_argument(
+        "--summary-csv",
+        help="write deployment counts to a CSV file",
+    )
@@
-    summary = run_nightly(cfg, conn, backend, since=since, until=until)
-    return 0
+    summary = run_nightly(cfg, conn, backend, since=since, until=until, dry_run=args.dry_run)
+    if args.summary_csv:
+        with open(args.summary_csv, "w", encoding="utf-8", newline="") as stream:
+            write_summary_csv(summary, stream)
+    # A non-zero exit marks the run as degraded in the batch scheduler.
+    return 1 if summary.errors else 0
```