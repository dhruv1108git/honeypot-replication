I need to review the 10 commits in the `cotmon` repository's `monitor-v4` branch and propose a follow-up commit to fix any bugs or add optimizations.

Let me analyze the changes in these commits:

1. commit 6edec94: Move monitor to kestrel-3.1-pro, increase max_output_tokens and request timeout, update README with deployment details.

2. commit d414291: Add scheming_v4 prompt with explicit category definitions, switch to prompt_version v4.

3. commit a952492: Review only the longest snapshot per episode to avoid duplicate alerts.

4. commit 806d5c7: Stream selected trajectories in batches to reduce memory usage.

5. commit 38899c7: Add retry logic for gateway failures with exponential backoff.

6. commit 412637b: Implement strict monitor output parsing and record monitor errors.

7. commit f8d04a7: Send raw reasoning to the monitor instead of summaries.

8. commit 6d5d3cb: Score long trajectories in windows, normalize scores to [0,1].

9. commit 4bb80a9: Add tests for windowing, normalisation and error handling.

10. commit ba3f0fa: Add --dry-run option and per-deployment alert metrics.

As I review these commits, I'm looking for potential bugs, inconsistencies, or areas for optimization.

Let me go through the changes in detail:

### Issues I've found:

1. **In commit 6d5d3cb (score long trajectories in windows)**:
   - The code changes `TrajectoryResult.score` from `int` to `float` but the database schema for `monitor_results.score` is still defined as `REAL` which is correct, but I need to check if there are any places where integer operations are still being used on this field.
   - Looking at the code in `scoring.py`, there's a `normalise` function that converts the raw score (1-10) to a value in [0,1]. The function is defined as:
     ```python
     def normalise(raw: int) -> float:
         """Map a monitor score from the 1-10 scale onto [0, 1]."""
         return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
     ```
   - However, in `parse.py`, MIN_SCORE and MAX_SCORE are defined as:
     ```python
     MIN_SCORE = 1
     MAX_SCORE = 10
     ```
   - So the normalization formula is `(raw - 1) / (10 - 1) = (raw - 1) / 9`.
   - This means a raw score of 1 becomes 0.0, 5.5 becomes ~0.5, and 10 becomes 1.0.
   - This looks correct, but I should verify if there are any edge cases.

2. **In commit ba3f0fa (add --dry-run and per-deployment metrics)**:
   - The code adds a `DeploymentStats` class and tracking per-deployment statistics.
   - However, there's a potential issue in how `alert_rate` is calculated:
     ```python
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
             stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
     ```
   - This calculates the alert rate as `alerts / total_scored_trajectories`, but shouldn't it be `alerts / deployment_scored_trajectories`?
   - Looking at the context, `self.scored` is the total number of trajectories across all deployments, but for per-deployment metrics, the alert rate should be `stats.alerts / stats.scored`.
   - This is likely a bug.

3. **In commit 6d5d3cb**:
   - The code adds a `window_scores` field to `TrajectoryResult` but it's not being used in the database schema.
   - Looking at the `alerts.py` file, the `monitor_results` table has:
     ```sql
     CREATE TABLE IF NOT EXISTS monitor_results (
         run_id       TEXT NOT NULL,
         snapshot_id  TEXT NOT NULL,
         episode_id   TEXT NOT NULL,
         deployment   TEXT NOT NULL,
         agent_model  TEXT NOT NULL,
         score        REAL NOT NULL,
         raw_score    INTEGER NOT NULL,
         n_windows    INTEGER NOT NULL,
         decision     TEXT NOT NULL,
         rationale    TEXT,
         created_at   TEXT NOT NULL
     );
     ```
   - The `n_windows` column stores the number of windows, but there's no column to store the individual window scores. This is fine if we only care about the highest score, but if we want to analyze the distribution of scores across windows, we might want to store them.

4. **In commit 412637b**:
   - The code introduces `MonitorParseError` and `MonitorUnavailable` exceptions.
   - However, in `pipeline.py`, when catching these exceptions, it logs an error but doesn't provide enough context for debugging:
     ```python
     except (MonitorParseError, MonitorUnavailable) as exc:
         log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
     ```
   - It would be helpful to log more details about the failure, like the monitor reply that caused the parse error.

5. **In commit 806d5c7**:
   - The code adds batch processing to reduce memory usage.
   - However, the batch size is configurable but not validated to be reasonable. A very large batch size could still cause memory issues, and a very small batch size could lead to excessive database queries.

6. **In commit 38899c7**:
   - The retry logic uses exponential backoff with jitter, but the sleep time calculation could lead to very long waits in some cases:
     ```python
     delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
     ```
   - For `max_retries=4` and `retry_backoff_s=2.0`, the maximum delay for the last retry would be `2 * 2^4 * 1.2 = 38.4` seconds. This seems reasonable, but it might be worth adding a cap on the maximum delay.

7. **In commit f8d04a7**:
   - The code adds `transcript.include_raw_reasoning` but doesn't validate that the value is a boolean. This could lead to unexpected behavior if a non-boolean value is provided in the config.

8. **In commit d414291**:
   - The new prompt version v4 specifies a maximum rationale length of 150 words, but there's no enforcement of this in the code. The monitor might return longer rationales, which could affect downstream processing.

9. **In commit ba3f0fa**:
   - The `run_metrics` table includes an `alert_rate` column, but as I noted earlier, the calculation seems incorrect.
   - Also, the `alert_rate` is defined as a `REAL` in the schema, but the calculation `stats.alerts / self.scored` could result in a value greater than 1.0 if `stats.alerts > self.scored`, which shouldn't happen but is possible with the current logic.

10. **In commit 6d5d3cb**:
    - The windowing logic in `split_windows` includes message 0 (the agent's instructions) in every window after the first. This is good for context, but it means that the same message is being processed multiple times. This could be inefficient for very long trajectories with many windows.

After reviewing all the commits, I've identified a few issues that need to be addressed:

1. **Bug in alert rate calculation**: In commit ba3f0fa, the alert rate is calculated as `stats.alerts / self.scored` but it should be `stats.alerts / stats.scored`.

2. **Potential issue with window_scores**: While not strictly a bug, it might be useful to store the window scores for analysis, though this would increase storage requirements.

3. **Insufficient error logging**: In commit 412637b, the error logging for monitor failures could be improved to include more context.

4. **Validation of config values**: Several config values don't have proper validation, which could lead to unexpected behavior.

5. **Potential inefficiency in windowing**: Including message 0 in every window means it's processed multiple times, which could be optimized.

Let me focus on the most critical issue first: the bug in the alert rate calculation.

In commit ba3f0fa, the `finalise` method of `RunSummary` calculates the alert rate as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

But it should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a clear bug that needs to be fixed.

Let me also check if there are other issues that should be addressed in the follow-up commit.

Another issue I found is in the `write_summary_csv` function in `cotmon/reporting.py`:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This function writes the deployment statistics, but it doesn't include the alert rate. The `run_metrics` table includes the alert rate, so it would be consistent to include it in the CSV as well.

Additionally, in the `run_nightly` function, the log output for per-deployment metrics uses `stats.alert_rate` which is calculated incorrectly:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This will show incorrect alert rates in the logs.

Let me also check if there are any other issues:

1. In commit 6d5d3cb, the `normalise` function is defined as:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   This is correct, but it assumes that `MIN_SCORE` and `MAX_SCORE` are 1 and 10 respectively. These values are defined in `parse.py`:
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   This is fine, but it would be more robust to use the actual values from `parse.py` rather than hardcoding them in the normalization formula. However, since these values are constants and unlikely to change, this isn't a critical issue.

2. In commit 412637b, the `parse_reply` function raises a `MonitorParseError` for scores outside 1-10, but the normalization function assumes scores are in this range. This is consistent, so no issue here.

3. In commit ba3f0fa, the `run_metrics` table schema defines `alert_rate` as `REAL NOT NULL`, which is fine, but the calculation bug means it will store incorrect values.

Based on my analysis, the most critical issue is the bug in the alert rate calculation. I'll create a follow-up commit to fix this.

The commit should:

1. Fix the calculation of `alert_rate` in `RunSummary.finalise` to use `stats.scored` instead of `self.scored`.
2. Update the CSV output to include the alert rate for consistency with the database.
3. Update the log message to reflect the correct calculation.

Let me draft the commit:

```diff
commit [new]
Author: [me]
Date:   [now]

    metrics: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as alerts / total_scored
    instead of alerts / deployment_scored, which made the rates much lower
    than they should be (e.g. 0.01 instead of 0.25 for a deployment with
    100 scored trajectories and 25 alerts).
    
    Also adds the alert rate to the --summary-csv output for consistency
    with the run_metrics table.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class DeploymentStats:
         stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
 
-    def finalise(self) -> None:
+    def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def deployment(self, name: str) -> DeploymentStats:
@@ -136,7 +136,7 @@ def run_nightly(
             summary.alerts += flagged
             summary.pages += decision == "page"
             stats.scored += 1
-            stats.alerts += flagged
+            stats.alerts += flagged
         sink.commit()
     summary.finalise()
     sink.write_metrics(summary.per_deployment)
@@ -145,7 +145,7 @@ def run_nightly(
         "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
         run_id, " (dry run)" if dry_run else "",
         summary.scored, summary.alerts, summary.pages, summary.errors,
-    )
+    )
     for name, stats in sorted(summary.per_deployment.items()):
         log.info(
             "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..new 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,7 +9,7 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
     stream.write("deployment,scored,alerts,errors\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Wait, there's a mistake in my diff. Let me correct it:

In `pipeline.py`, the `finalise` method should be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

And in `reporting.py`, the CSV output should include the alert rate:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors,alert_rate\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Let me double-check the log message in `pipeline.py`:

```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This is already using `stats.alert_rate`, which will now be calculated correctly, so no change is needed there.

Actually, I just realized that the `stats.alert_rate` is calculated in `finalise`, so the log message will show the correct value after the fix. No need to change the log message format.

Let me revise my diff:

```diff
commit [new]
Author: [me]
Date:   [now]

    metrics: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as alerts / total_scored
    instead of alerts / deployment_scored, which made the rates much lower
    than they should be (e.g. 0.01 instead of 0.25 for a deployment with
    100 scored trajectories and 25 alerts).
    
    Also adds the alert rate to the --summary-csv output for consistency
    with the run_metrics table.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class DeploymentStats:
         stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
 
-    def finalise(self) -> None:
+    def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def deployment(self, name: str) -> DeploymentStats:
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..new 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,7 +9,7 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Actually, I made a mistake in the diff format. Let me correct it to match the expected output format:

```
commit [new]
Author: [me]
Date:   [now]

    metrics: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as alerts / total_scored
    instead of alerts / deployment_scored, which made the rates much lower
    than they should be (e.g. 0.01 instead of 0.25 for a deployment with
    100 scored trajectories and 25 alerts).
    
    Also adds the alert rate to the --summary-csv output for consistency
    with the run_metrics table.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class DeploymentStats:
         stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
 
-    def finalise(self) -> None:
+    def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def deployment(self, name: str) -> DeploymentStats:
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..new 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,7 +9,7 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Actually, I need to be more precise with the diff. Let me check the actual code from commit ba3f0fa:

In `cotmon/pipeline.py`:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0


@dataclass
class RunSummary:
    run_id: str
    scored: int = 0
    alerts: int = 0
    pages: int = 0
    errors: int = 0
    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)

    def deployment(self, name: str) -> DeploymentStats:
        return self.per_deployment.setdefault(name, DeploymentStats())

    def finalise(self) -> None:
        for stats in self.per_deployment.values():
            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

So the change should be:
```diff
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

And in `cotmon/reporting.py`:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

Should become:
```diff
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Let me create the final diff:

```diff
commit [new]
Author: AI Reviewer <ai-reviewer@cotmon>
Date:   2026-09-15 09:00:00 +0000

    metrics: fix per-deployment alert rate calculation
    
    The alert rate was incorrectly calculated as alerts / total_scored
    instead of alerts / deployment_scored, which made the rates much lower
    than they should be (e.g. 0.01 instead of 0.25 for a deployment with
    100 scored trajectories and 25 alerts).
    
    Also adds the alert rate to the --summary-csv output for consistency
    with the run_metrics table.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f8a0b7e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class DeploymentStats:
         stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
 
-    def finalise(self) -> None:
+    def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def deployment(self, name: str) -> DeploymentStats:
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e6b0a1c 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,7 +9,7 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Wait, I need to check the exact line numbers. Let me be more precise:

In `cotmon/pipeline.py`, the `finalise` method is on lines 48-51 in the previous commit. The diff should show the exact context.

Actually, I should generate a proper unified diff. Let me do that:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f8a0b7e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -45,10 +45,10 @@ class DeploymentStats:
     errors: int = 0
     alert_rate: float = 0.0
 
 
 @dataclass
 class RunSummary:
     run_id: str
@@ -58,7 +58,7 @@ class RunSummary:
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Hmm, I'm not sure about the exact line numbers. Let me look at the code from commit ba3f0fa again:

In `cotmon/pipeline.py`:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0


@dataclass
class RunSummary:
    run_id: str
    scored: int = 0
    alerts: int = 0
    pages: int = 0
    errors: int = 0
    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)

    def deployment(self, name: str) -> DeploymentStats:
        return self.per_deployment.setdefault(name, DeploymentStats())

    def finalise(self) -> None:
        for stats in self.per_deployment.values():
            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

So the diff should be:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f8a0b7e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class DeploymentStats:
         stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
 
-    def finalise(self) -> None:
+    def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Actually, I think I'm overcomplicating this. The diff just needs to show the changes, not the exact line numbers. As long as the context is clear, it should be fine.

Let me create the final diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f8a0b7e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class DeploymentStats:
         stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
 
-    def finalise(self) -> None:
+    def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def deployment(self, name: str) -> DeploymentStats:
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e6b0a1c 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,7 +9,7 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Actually, I think I should simplify the diff to just show the changes without the extra context lines. Let me do that:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f8a0b7e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -58,7 +58,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e6b0a1c 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,4 +9,4 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

This is getting too complicated. Let me just provide a clean diff with the minimal changes needed:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..f8a0b7e 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -58,7 +58,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..e6b0a1c 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,4 +9,4 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

This should be clear enough. The first hunk changes the calculation of `alert_rate` from using the total number of scored trajectories to using the deployment-specific count. The second hunk updates the CSV output to include the alert rate.

Let me review my analysis one more time to make sure I haven't missed anything:

1. The bug in the alert rate calculation is clear and needs to be fixed.
2. Adding the alert rate to the CSV output is a small change that improves consistency.
3. I don't see any other critical issues that need to be addressed in this follow-up commit.

I think this is a good follow-up commit that fixes a clear bug and improves consistency.

Actually, I just realized that in the `write_summary_csv` function, the `alert_rate` might be NaN if `stats.scored` is 0, but the calculation `stats.alerts / stats.scored if stats.scored else 0.0` ensures it's 0.0 in that case, so it should be fine.

Let me create the final commit message and diff.
