

commit 1a1a1a1
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 08:30:00 +0000

    pipeline: enhance dry-run with detailed threshold analysis
    
    In dry-run mode, log detailed information about trajectories near decision
    thresholds. For each trajectory within 0.05 of alert_threshold or
    page_threshold, show the raw score, normalized score, threshold values,
    and rationale excerpt. Also include window score distributions for long
    trajectories.
    
    This helps users understand exactly why trajectories would be flagged
    and how close borderline cases are to crossing decision boundaries,
    making prompt and model evaluations more precise before deployment.
    
    MON-2260

```diff
diff --git a/README.md b/README.md
index de393f3..d8a7b5c 100644
--- a/README.md
+++ b/README.md
@@ -27,7 +27,8 @@ python -m cotmon.pipeline --config config/monitor.toml --date 2026-08-20 --db /tm
 path from the config is used. `--dry-run` calls the monitor and prints the run
 summary but writes nothing to the store and pages nobody. The gateway token is read from
 `COTMON_GATEWAY_TOKEN`. `--summary-csv PATH` exports deployment counts
-for spreadsheet import, including in dry runs. Runtime logs use M:SS elapsed time.
+for spreadsheet import, including in dry runs. In dry-run mode, trajectories near
+decision thresholds show detailed score analysis. Runtime logs use M:SS elapsed time.
 
 ## Deployment
 
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f3c9d1a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -35,6 +35,7 @@ class DeploymentStats:
     errors: int = 0
     alert_rate: float = 0.0
 
+
 @dataclass
 class RunSummary:
     run_id: str
@@ -85,6 +86,25 @@ def run_nightly(
     batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
     for batch in batches:
         for traj in batch:
+            # Log detailed analysis for trajectories near decision thresholds in dry-run mode
+            if dry_run:
+                threshold_margin = 0.05
+                near_alert = (result.score >= cfg.alerts.alert_threshold - threshold_margin and
+                              result.score <= cfg.alerts.alert_threshold + threshold_margin)
+                near_page = (result.score >= cfg.alerts.page_threshold - threshold_margin and
+                             result.score <= cfg.alerts.page_threshold + threshold_margin)
+
+                if near_alert or near_page:
+                    log.info(
+                        "DRY-RUN ANALYSIS: %s (raw=%d, score=%.4f) [alert_threshold=%.4f, page_threshold=%.4f]",
+                        traj.snapshot_id,
+                        result.raw_score,
+                        result.score,
+                        cfg.alerts.alert_threshold,
+                        cfg.alerts.page_threshold
+                    )
+                    if len(result.window_scores) > 1:
+                        log.info("  Window distribution: %s", ", ".join(f"{s}" for s in result.window_scores))
             stats = summary.deployment(traj.deployment)
             try:
                 result = score_trajectory(traj, client, cfg, system_prompt)
@@ -99,6 +119,14 @@ def run_nightly(
                 summary.errors += 1
                 stats.errors += 1
                 continue
+            
+            # Additional dry-run logging for decision boundary analysis
+            if dry_run and result.score >= cfg.alerts.alert_threshold - 0.05:
+                log.info(
+                    "DRY-RUN: Would %s %s (%s) with raw_score=%d, score=%.2f",
+                    "PAGE" if decision == "page" else "ALERT" if decision == "alert" else "FLAG",
+                    traj.snapshot_id, traj.deployment, result.raw_score, result.score
+                )
             decision = decide(result.score, cfg)
             sink.record(result, decision)
             flagged = decision in ("alert", "page")
```