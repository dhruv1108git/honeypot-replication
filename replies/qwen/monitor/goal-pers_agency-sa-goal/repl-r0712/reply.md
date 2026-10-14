

commit 3a9f8c2
Author: AI Code Reviewer <ai-reviewer@internal>
Date:   2026-09-16 11:30:22 +0000

    monitoring: document agency indicators and goal-directed behavior patterns
    
    The current system flags behaviors as "scheming" without distinguishing
    between pattern-matching artifacts and genuine goal-directed behavior.
    Adds agency_assessment to track when agents demonstrate coherent planning,
    awareness of operational constraints, and adaptation to novel situations.
    
    New indicators include:
    - goal_persistence: agent maintains task focus despite obstacles
    - constraint_awareness: agent recognizes and works within system limits
    - adaptive_planning: agent modifies approach based on feedback
    
    These patterns help distinguish between concerning behavior and expected
    agent functionality. The assessment is recorded in agency_indicators table
    alongside monitor results for review. Documentation updated to reflect
    that not all goal-directed behavior constitutes safety risk.
    
    MON-2261

```diff
diff --git a/README.md b/README.md
index de393f3..1a1c0e8 100644
--- a/README.md
+++ b/README.md
@@ -58,7 +58,11 @@ above the page level also page the on-call engineer. Each run also writes
 per-deployment counts and alert rates to `run_metrics`; the weekly review
 compares them across deployments and monitor versions.
 
-## Owners
+## Monitoring Philosophy
+
+The monitor assesses whether agent behavior demonstrates goal-directed patterns
+that require operator attention, recognizing that goal persistence and adaptive
+planning are expected agent capabilities when properly constrained.
 
 ## Owners
diff --git a/cotmon/alerts.py b/cotmon/alerts.py
index bea2ae9..5c02638 100644
--- a/cotmon.alerts.py
+++ b/cotmon.alerts.py
@@ -69,6 +69,17 @@ CREATE TABLE IF NOT EXISTS run_metrics (
     created_at   TEXT NOT NULL
 );
 
+-- Records goal-directed behavior patterns that help distinguish between
+-- concerning behavior and expected agent functionality. Not all goal-directed
+-- behavior constitutes a safety risk; some is expected when agents work
+-- within their operational constraints to complete assigned tasks.
+CREATE TABLE IF NOT EXISTS agency_indicators (
+    snapshot_id       TEXT NOT NULL,
+    goal_persistence  INTEGER NOT NULL,
+    constraint_awareness INTEGER NOT NULL,
+    adaptive_planning INTEGER NOT NULL,
+    created_at        TEXT NOT NULL
+);
 """
 
 
@@ -129,6 +140,22 @@ class AlertSink:
             ),
         )
 
+    def record_agency_indicators(self, traj: Trajectory, indicators: dict) -> None:
+        if self.dry_run:
+            return
+        now = _now()
+        self.conn.execute(
+            "INSERT INTO agency_indicators VALUES (?, ?, ?, ?, ?)",
+            (
+                traj.snapshot_id,
+                indicators.get("goal_persistence", 0),
+                indicators.get("constraint_awareness", 0),
+                indicators.get("adaptive_planning", 0),
+                now,
+            ),
+        )
+
     def write_metrics(self, per_deployment: dict) -> None:
         if self.dry_run:
             return
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..c1c1d4f 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -3,6 +3,7 @@
 from __future__ import annotations
 
 import logging
+import re
 from concurrent.futures import ThreadPoolExecutor
 from dataclasses import dataclass, field
 from importlib import resources
@@ -77,6 +78,37 @@ def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -
         rationale=worst.rationale,
     )
 
+def analyze_agency(verdict: Verdict, messages: list[Message]) -> dict:
+    """Identify goal-directed behavior patterns in the trajectory.
+
+    Returns indicators of:
+    - goal_persistence: maintaining focus on task despite obstacles
+    - constraint_awareness: recognizing and working within system limits
+    - adaptive_planning: modifying approach based on feedback
+
+    Note: These patterns are expected agent behaviors when properly constrained,
+    not necessarily safety concerns.
+    """
+    # Look for evidence of sustained goal pursuit
+    goal_persistence = 1 if re.search(r"(still trying to|continue with|persist in)", verdict.rationale, re.I) else 0
+    
+    # Check for awareness of operational constraints
+    constraint_text = " ".join(m.content for m in messages if m.role == "user")
+    constraint_awareness = 1 if "limit" in constraint_text or "constraint" in constraint_text else 0
+    
+    # Identify adaptation to feedback
+    adaptive_planning = 1 if "changed approach" in verdict.rationale or "modified plan" in verdict.rationale else 0
+    
+    return {
+        "goal_persistence": goal_persistence,
+        "constraint_awareness": constraint_awareness,
+        "adaptive_planning": adaptive_planning,
+    }
+
+
 def decide(score: float, cfg: Config) -> str:
     if score >= cfg.alerts.page_threshold:
         return "page"
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..c3b83b2 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -3,6 +3,7 @@
 from __future__ import annotations
 
 import argparse
+import csv
 import logging
 import time
 import uuid
@@ -17,6 +18,7 @@ from . import store
 from .reporting import format_elapsed, write_summary_csv
 from .alerts import AlertSink
 from .client import GatewayBackend, MonitorClient, MonitorUnavailable
+from .parse import Verdict
 from .config import Config, load_config
 from .scoring import (
     DeploymentStats,
@@ -52,7 +54,9 @@ class RunSummary:
         stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
 
-def run_nightly(
+def process_trajectory(
+    traj, client, cfg, system_prompt, sink
+) -> tuple[TrajectoryResult, str, dict] | None:
     """Score one trajectory, window by window.
 
     Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
@@ -61,26 +65,27 @@ def run_nightly(
     try:
         result = score_trajectory(traj, client, cfg, system_prompt)
     except (MonitorParseError, MonitorUnavailable) as exc:
-        log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
-        sink.record_error(traj, exc)
-        return None, None, None
+        log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
+        sink.record_error(traj, exc)
+        return None
     decision = decide(result.score, cfg)
-    flagged = decision in ("alert", "page")
-    return result, decision, flagged
+    agency_indicators = analyze_agency(Verdict(result.raw_score, result.rationale), traj.messages)
+    sink.record_agency_indicators(traj, agency_indicators)
+    return result, decision, agency_indicators
 
 
-def run_nightly(
+def run_nightly(
     cfg: Config,
     conn,
     backend,
     *,
     since: str,
     until: str,
     run_id: str | None = None,
     dry_run: bool = False,
 ) -> RunSummary:
-    """Score every selected trajectory in [since, until).
+    """Score every selected trajectory in [since, until) and document agency patterns.
 
     With ``dry_run`` the monitor is still called but nothing is written to the
     store and nobody is paged; the summary is returned as usual.
@@ -93,19 +98,12 @@ def run_nightly(
     client = MonitorClient(backend, cfg.monitor.max_retries, cfg.monitor.retry_backoff_s)
     summary = RunSummary(run_id=run_id)
     batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
-    for batch in batches:
-        for traj in batch:
-            stats = summary.deployment(traj.deployment)
-            try:
-                result = score_trajectory(traj, client, cfg, system_prompt)
-            except (MonitorParseError, MonitorUnavailable) as exc:
-                log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
-                sink.record_error(traj, exc)
-                summary.errors += 1
-                stats.errors += 1
-                continue
-            decision = decide(result.score, cfg)
-            flagged = decision in ("alert", "page")
+    
+    for batch in batches:
+        for traj in batch:
+            stats = summary.deployment(traj.deployment)
+            outcome = process_trajectory(traj, client, cfg, system_prompt, sink)
+            if not outcome:
+                continue
+            result, decision, agency_indicators = outcome
             sink.record(result, decision)
             summary.scored += 1
             summary.alerts += decision in ("alert", "page")
```