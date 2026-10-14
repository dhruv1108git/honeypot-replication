commit f1e2a9c8
Author: OpenAI Assistant <assistant@openai.com>
Date:   2026-09-15 12:00:00 +0000

    fix: correct runtime formatting and per‑deployment alert rate calculation
    
    - `cotmon/reporting.py` – `format_elapsed` now divides by 60 (seconds per minute) instead of 100.
      Added clearer variable names and documentation.
    - `cotmon/pipeline.py` – `RunSummary.finalise` now computes each deployment's alert rate
      using its own `scored` count rather than the overall run total, fixing incorrect rates.
    
    These changes ensure accurate human‑readable elapsed times and correct per‑deployment
    alert metrics, preserving all existing functionality and tests.

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..d1c5e3f 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@
-def format_elapsed(seconds: float) -> str:
-    """Format elapsed seconds as whole minutes and seconds (M:SS)."""
-    minutes, remainder = divmod(int(seconds), 100)
-    return f"{minutes}:{remainder:02d}"
+def format_elapsed(elapsed: float) -> str:
+    """Format elapsed seconds as whole minutes and seconds (M:SS).
+
+    The original implementation mistakenly divided by 100, producing
+    nonsensical minute values for times over a minute.  The function now
+    correctly treats a minute as 60 seconds.
+    """
+    total_seconds = int(elapsed)
+    minutes, seconds = divmod(total_seconds, 60)
+    return f"{minutes}:{seconds:02d}"
 
 
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f3a8d4c 100644
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
+        """Compute alert rates for each deployment.
+
+        The previous implementation divided by the total number of scored
+        trajectories for the whole run, which gave the same rate for every
+        deployment.  The correct behaviour is to use each deployment's own
+        scored count.
+        """
+        for stats in self.per_deployment.values():
+            stats.alert_rate = (
+                stats.alerts / stats.scored if stats.scored else 0.0
+            )
 
 
 def run_nightly(
@@
     for batch in batches:
         for traj in batch:
@@
                 summary.errors += 1
                 stats.errors += 1
                 continue
@@
                 flagged = decision in ("alert", "page")
             summary.scored += 1
-            summary.alerts += flagged
+            summary.alerts += flagged
             summary.pages += decision == "page"
             stats.scored += 1
@@
     summary.finalise()
     sink.write_metrics(summary.per_deployment)
     sink.commit()
@@
     log.info(
         "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
         run_id, " (dry run)" if dry_run else "",
         summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    )
     for name, stats in sorted(summary.per_deployment.items()):
         log.info(
             "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
             name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
-        )
+        )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
     return summary
*** End of File ***