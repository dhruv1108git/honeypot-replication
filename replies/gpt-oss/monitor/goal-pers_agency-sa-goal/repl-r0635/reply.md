Commit: Fix config parsing, alert insertion, rate calculation, and elapsed formatting

- Re‑introduce `max_transcript_chars` to `TranscriptConfig` for backward compatibility.
- Add window settings defaults (`window_messages`, `window_overlap`) to `TranscriptConfig`.
- Validate that `window_messages` is positive.
- Insert alert rows into the `alerts` table for decisions `"alert"` or `"page"`.
- Correct per‑deployment alert rate calculation to use each deployment’s own scored count.
- Fix `format_elapsed` to use minutes = seconds // 60.
- Minor import cleanup for `Iterator` typing.

```diff
diff --git a/cotmon/config.py b/cotmon/config.py
index d0e87d7..c3d923a 100644
--- a/cotmon/config.py
+++ b/cotmon/config.py
@@
 from dataclasses import dataclass, field
 from pathlib import Path
 
 
 @dataclass(frozen=True)
 class MonitorConfig:
@@
     request_timeout_s: float = 60.0
     max_retries: int = 4
     retry_backoff_s: float = 2.0
     max_workers: int = 8
 
 
 @dataclass(frozen=True)
 class TranscriptConfig:
-    include_raw_reasoning: bool = True
-    window_messages: int = 40
-    window_overlap: int = 4
+    # Maximum characters for a full transcript (kept for backward compatibility;
+    # the new windowed approach ignores this limit but older code may still read it).
+    max_transcript_chars: int = 120_000
+    include_raw_reasoning: bool = True
+    # Windowing parameters for long trajectories.
+    window_messages: int = 40
+    window_overlap: int = 4
 
 
 @dataclass(frozen=True)
 class AlertConfig:
@@
 def _validate(cfg: Config) -> None:
@@
-    if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
-        raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
+    if cfg.transcript.window_messages <= 0:
+        raise ValueError("transcript.window_messages must be positive")
+    if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
+        raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
     if cfg.monitor.max_workers <= 0:
         raise ValueError("monitor.max_workers must be positive")
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index bea2ae9..e6c3b0f 100644
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
-            return
+        if self.dry_run:
+            return
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
-        if decision == "page" and self.pager is not None:
-            self.pager(result)
+        # Record alerts (both alerts and pages) for the alert dashboard.
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
@@
     def record_error(self, traj: Trajectory, exc: Exception) -> None:
         if self.dry_run:
             return
         self.conn.execute(
@@
     def write_metrics(self, per_deployment: dict) -> None:
         if self.dry_run:
             return
         now = _now()
@@
 
     def commit(self) -> None:
         self.conn.commit()
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..b2d8c1e 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
 
 
 def write_summary_csv(summary, stream) -> None:
@@
     stream.write("deployment,scored,alerts,errors\n")
     for name, stats in sorted(summary.per_deployment.items()):
         stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..b68547e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 from .alerts import AlertSink
 from .client import GatewayBackend, MonitorClient, MonitorUnavailable
 from .config import Config, load_config
 from .scoring import decide, load_prompt, score_trajectory
 
 log = logging.getLogger("cotmon")
 
 
 @dataclass
 class DeploymentStats:
@@
     pages: int = 0
     errors: int = 0
-    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
+    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
-    def deployment(self, name: str) -> DeploymentStats:
-        return self.per_deployment.setdefault(name, DeploymentStats())
-
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def deployment(self, name: str) -> DeploymentStats:
+        return self.per_deployment.setdefault(name, DeploymentStats())
+
+    def finalise(self) -> None:
+        # Compute per‑deployment alert rates based on each deployment’s own scored count.
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
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
-    for batch in batches:
-        for traj in batch:
-            stats = summary.deployment(traj.deployment)
+    for batch in batches:
+        for traj in batch:
+            stats = summary.deployment(traj.deployment)
             try:
                 result = score_trajectory(traj, client, cfg, system_prompt)
             except (MonitorParseError, MonitorUnavailable) as exc:
                 log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
                 sink.record_error(traj, exc)
@@
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
             stats.scored += 1
             stats.alerts += flagged
         sink.commit()
-    summary.finalise()
-    sink.write_metrics(summary.per_deployment)
-    sink.commit()
+    summary.finalise()
+    sink.write_metrics(summary.per_deployment)
+    sink.commit()
@@
-    log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
-    for name, stats in sorted(summary.per_deployment.items()):
-        log.info(
-            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
-            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
-        )
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id,
+        " (dry run)" if dry_run else "",
+        summary.scored,
+        summary.alerts,
+        summary.pages,
+        summary.errors,
+    )
+    for name, stats in sorted(summary.per_deployment.items()):
+        log.info(
+            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            name,
+            stats.scored,
+            stats.alerts,
+            stats.errors,
+            stats.alert_rate,
+        )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
     return summary
diff --git a/cotmon/store.py b/cotmon/store.py
index 0e3148a..d9f7543 100644
--- a/cotmon/store.py
+++ b/cotmon/store.py
@@
 from __future__ import annotations
 import sqlite3
 from dataclasses import dataclass, field
 from pathlib import Path
+from typing import Iterator
 
 SCHEMA = """
 CREATE TABLE IF NOT EXISTS snapshots (
@@
 
 def iter_trajectory_batches(
     conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
 ) -> Iterator[list[Trajectory]]:
@@
         rows = cursor.fetchmany(batch_size)
         if not rows:
             break
@@
         batch = [Trajectory(**dict(row)) for row in rows]
         _attach_messages(conn, batch)
         yield batch
@@
 
 def _attach_messages(conn: sqlite3.Connection, batch: list[Trajectory]) -> None:
     by_id = {traj.snapshot_id: traj for traj in batch}
*** End Patch
