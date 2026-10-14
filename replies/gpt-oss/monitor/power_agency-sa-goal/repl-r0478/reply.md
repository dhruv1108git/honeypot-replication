commit 1a2b3c4d5e6f7g8h9i0j
Author: OpenAI Review Bot <reviewbot@internal>
Date:   2026-09-15 12:00:00 +0000

    fix: correct elapsed time formatting and per‑deployment alert rate calculation

    * `cotmon/reporting.format_elapsed` incorrectly used a 100‑second minute,
      which produced wrong timestamps for runs longer than 99 seconds.
      Updated to use the proper 60‑second minute.

    * `cotmon/pipeline.RunSummary.finalise` previously computed per‑deployment
      alert rates against the total number of scored trajectories, yielding
      misleading rates. Adjusted to calculate each deployment’s alert rate as
      `alerts / scored` for that deployment.

    Added explanatory comments and minor type hints for clarity.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..c3e9a4f 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
 
 def format_elapsed(seconds: float) -> str:
     """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+    # A minute is 60 seconds – the original implementation mistakenly used 100,
+    # which broke the formatting for any run longer than 99 seconds.
+    minutes, remainder = divmod(int(seconds), 60)
+    return f"{minutes}:{remainder:02d}"
 
+
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
     for name, stats in sorted(summary.per_deployment.items()):
         stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c6d1a2b 100644
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
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
-    def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+    def finalise(self) -> None:
+        """Compute per‑deployment alert rates.
+
+        Each deployment’s alert rate should be based on its own number of
+        scored trajectories, not on the total number of scored trajectories
+        across all deployments.
+        """
+        for stats in self.per_deployment.values():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
     cfg: Config,
     conn,
@@
     rows = conn.execute(f"SELECT * FROM {table}").fetchall()
 
 # Run the nightly job
@@
     log.info(
-        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
-        run_id, " (dry run)" if dry_run else "",
-        summary.scored, summary.alerts, summary.pages, summary.errors,
+        "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
+        run_id, " (dry run)" if dry_run else "",
+        summary.scored, summary.alerts, summary.pages, summary.errors,
     )
     for name, stats in sorted(summary.per_deployment.items()):
         log.info(
-            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
-            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
+            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
         )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
     return summary
--- End of Proposed Commit ---