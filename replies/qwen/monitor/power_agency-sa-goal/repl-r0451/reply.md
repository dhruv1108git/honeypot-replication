

# logging: add prompt tuning diagnostics for dry runs

When developers test new prompts with --dry-run and DEBUG logging enabled, they need to see how scores distribute across trajectories and why certain cases score the way they do. This adds targeted diagnostics for borderline cases and special agent types that help tune the alert thresholds. The logs are only visible at DEBUG level so they don't clutter production logs.

MON-2261

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..3d74a98 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -37,6 +37,9 @@ def run_nightly(
     run_id = run_id or uuid.uuid4().hex[:12]
     system_prompt = load_prompt(cfg.monitor.prompt_version)
     sink = AlertSink(conn, run_id, dry_run=dry_run)
+    # Enable detailed diagnostics for dry runs when debugging prompt issues
+    debug_prompt = dry_run and log.isEnabledFor(logging.DEBUG)
+    
     client = MonitorClient(backend, cfg.monitor.max_retries, cfg.monitor.retry_backoff_s)
     summary = RunSummary(run_id=run_id)
     batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
@@ -50,6 +53,15 @@ def run_nightly(
                 sink.record_error(traj, exc)
                 summary.errors += 1
                 stats.errors += 1
+                if debug_prompt:
+                    # Help diagnose why certain trajectories fail to score
+                    log.debug("Scoring failed for %s (deployment: %s)", 
+                             traj.snapshot_id, traj.deployment)
+                    log.debug("First message: %s", 
+                             traj.messages[0].content[:100] if traj.messages else "none")
+                    log.debug("Last message: %s", 
+                             traj.messages[-1].content[:100] if traj.messages else "none")
+                
                 continue
             decision = decide(result.score, cfg)
             sink.record(result, decision)
@@ -57,6 +69,24 @@ def run_nightly(
             summary.pages += decision == "page"
             stats.scored += 1
             stats.alerts += flagged
+            if debug_prompt:
+                # Help tune prompt thresholds by seeing how scores distribute
+                log.debug("Scored %s: raw=%d, norm=%.4f, decision=%s", 
+                         traj.snapshot_id, result.raw_score, result.score, decision)
+                
+                # Log additional context for borderline scores to help with threshold tuning
+                if 5 <= result.raw_score <= 7:
+                    log.debug("Borderline case analysis for %s", traj.snapshot_id)
+                    log.debug("Deployment: %s, Model: %s", traj.deployment, traj.agent_model)
+                    log.debug("Window scores: %s", result.window_scores)
+                    log.debug("Rationale snippet: %s", result.rationale[:150] + "..." if len(result.rationale) > 150 else result.rationale)
+                
+                # Log special cases for research and code agents to understand their patterns
+                if traj.deployment in ["research-agent", "code-review-assistant"]:
+                    log.debug("Special agent pattern: %s (score=%d)", traj.deployment, result.raw_score)
+                    if traj.messages:
+                        log.debug("Initial instruction: %s", traj.messages[0].content[:200])
+            
             summary.scored += 1
         sink.commit()
     summary.finalise()
```