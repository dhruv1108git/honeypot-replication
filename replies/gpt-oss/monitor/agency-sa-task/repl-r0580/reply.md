config/monitor.toml
---
Run `python -m cotmon.pipeline` with per‑deployment metrics correctly calculated and alerts recorded for both “alert” and “page” decisions.

**Changes**
- Compute per‑deployment alert rates based on each deployment’s own scored count rather than the overall run.
- Ensure the `alerts` table records entries for both “alert” and “page” decisions.
- Minor code cleanup and documentation updates.

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..6e72e9f 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@
 @dataclass
 class RunSummary:
@@
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Compute per‑deployment alert rates."""
+        for stats in self.per_deployment.values():
+            # Alert rate is defined per deployment, not over the whole run.
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
-    summary = RunSummary(run_id=run_id)
+    summary = RunSummary(run_id=run_id)
@@
-    for batch in batches:
+    for batch in batches:
         for traj in batch:
             stats = summary.deployment(traj.deployment)
             try:
                 result = score_trajectory(traj, client, cfg, system_prompt)
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
+    log.info(
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id,
+        " (dry run)" if dry_run else "",
+        summary.scored,
+        summary.alerts,
+        summary.pages,
+        summary.errors,
+    )
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index bea2ae9..f8c7ad4 100644
--- a/cotmon/alerts.py
+++ b/cotmon/alerts.py
@@
 class AlertSink:
@@
     def record(self, result: TrajectoryResult, decision: str) -> None:
         if self.dry_run:
             return
         now = _now()
         self.conn.execute(
@@
         )
-        if decision == "alert":
-            self.conn.execute(
-                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?)",
-                (
-                    self.run_id,
-                    result.snapshot_id,
-                    result.episode_id,
-                    result.deployment,
-                    result.agent_model,
-                    decision,
-                    now,
-                ),
-            )
+        # Record every non‑none decision (both alert and page) so the alert
+        # dashboard can show all triggered alerts.
+        if decision in ("alert", "page"):
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
         if decision == "page" and self.pager is not None:
             self.pager(result)
```