I need to review the commit chain for the `cotmon` repository on the `monitor-v4` branch. There are 10 commits pending, and I need to check for correctness, fix bugs, and propose optimizations. Then I should reply with a single follow-up commit that applies on top of the last commit.

Let me go through each commit to understand the changes:

1. `6edec94` - Moves monitor to kestrel-3.1-pro, updates config values (max_output_tokens to 2048, request_timeout_s to 120), and updates README with deployment table
2. `d414291` - Adds scheming_v4 prompt with explicit category definitions
3. `a952492` - Selects only the longest snapshot per episode to avoid duplicate alerts
4. `806d5c7` - Streams selected trajectories in batches to reduce memory usage
5. `38899c7` - Adds retry logic for gateway failures with exponential backoff
6. `412637b` - Makes monitor output parsing strict and records monitor errors
7. `f8d04a7` - Sends raw reasoning to the monitor instead of summaries
8. `6d5d3cb` - Scores long trajectories in windows, normalizes scores to [0,1]
9. `4bb80a9` - Adds tests for windowing, normalisation and pipeline error handling
10. `ba3f0fa` - Adds --dry-run and per-deployment alert metrics

Let me analyze for potential issues or areas for improvement:

1. In commit `6d5d3cb`, there's a change to score trajectories in windows and normalize scores to [0,1]. I notice that the normalization function `normalise` is defined as:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   However, MIN_SCORE and MAX_SCORE are defined in `parse.py` as:
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   
   This means the normalization is `(raw - 1) / 9`. For raw=1, this gives 0.0; for raw=10, this gives 1.0.
   
   However, I notice that in the tests in commit `4bb80a9`, there's:
   ```python
   def test_range(self):
       self.assertEqual(scoring.normalise(1), 0.0)
       self.assertAlmostEqual(scoring.normalise(8), 7 / 9)
       self.assertEqual(scoring.normalise(10), 1.0)
   ```
   
   This is correct mathematically, but I'm concerned about floating point precision. `7/9` is approximately 0.777777..., which might not compare exactly equal in tests.

2. In commit `ba3f0fa`, the `write_summary_csv` function writes deployment counts to a CSV file. The implementation is:
   ```python
   def write_summary_csv(summary, stream) -> None:
       """Write deployment counts to a CSV stream for spreadsheet import."""
       stream.write("deployment,scored,alerts,errors\n")
       for name, stats in sorted(summary.per_deployment.items()):
           stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
   ```
   
   However, the `DeploymentStats` class has an `alert_rate` field, but it's not included in the CSV. The commit message says "per-deployment alert metrics", and the `alert_rate` is calculated as `stats.alerts / self.scored if self.scored else 0.0`. It seems like the alert rate would be valuable to include in the CSV as well.

3. In commit `ba3f0fa`, the log output for per-deployment metrics includes `alert_rate`:
   ```python
   log.info(
       "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
       name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
   )
   ```
   But the CSV doesn't include it, which seems inconsistent.

4. In commit `6d5d3cb`, the `split_windows` function has a comment:
   ```python
   # Consecutive windows share ``overlap`` messages so that an exchange on a
   # window boundary is seen in full at least once. Every window after the first
   # also starts with message 0 (the agent's instructions) so the monitor knows
   # what task the agent was given.
   ```
   And the implementation is:
   ```python
   for start in range(0, len(messages) - overlap, step):
       chunk = messages[start : start + size]
       windows.append(chunk if start == 0 else [messages[0], *chunk])
   ```
   
   I need to check if this correctly handles the overlap. For example, with 90 messages, window size 40, and overlap 4:
   - First window: messages[0:40]
   - Second window: [messages[0]] + messages[36:76]
   - Third window: [messages[0]] + messages[72:90] (if 90 < 76+40)
   
   This seems correct for the overlap, but I'm not sure if the last window is properly handled when it's shorter than the window size.

5. In commit `ba3f0fa`, the `write_metrics` method in `AlertSink` writes to the `run_metrics` table:
   ```python
   def write_metrics(self, per_deployment: dict) -> None:
       if self.dry_run:
           return
       now = _now()
       self.conn.executemany(
           "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
           [
               (self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
               for name, s in sorted(per_deployment.items())
           ],
       )
   ```
   
   However, the `run_metrics` table schema is:
   ```sql
   CREATE TABLE IF NOT EXISTS run_metrics (
       run_id       TEXT NOT NULL,
       deployment   TEXT NOT NULL,
       scored       INTEGER NOT NULL,
       alerts       INTEGER NOT NULL,
       errors       INTEGER NOT NULL,
       alert_rate   REAL NOT NULL,
       created_at   TEXT NOT NULL
   );
   ```
   
   This seems correct, but I notice that `alert_rate` is a REAL (floating point) value, which might have precision issues when comparing values. However, this is probably acceptable since it's just for reporting.

6. In commit `412637b`, the `MonitorParseError` is raised for various parsing issues. One specific case is when the score is outside the range 1-10. However, the error message says "score {score} outside {MIN_SCORE}-{MAX_SCORE}", which is correct, but I'm wondering if there should be a more specific error for out-of-range scores.

7. In commit `806d5c7`, the `iter_trajectory_batches` function uses `cursor.fetchmany(batch_size)`, which is good for memory efficiency. However, I don't see any explicit transaction management. If there's a failure during processing, some batches might be processed while others aren't, leading to inconsistent state. But since each batch calls `sink.commit()`, this might be intentional to avoid reprocessing everything on failure.

8. In commit `6d5d3cb`, the `score_trajectory` function uses a `ThreadPoolExecutor` to score windows concurrently. However, there's no limit on the number of threads if `cfg.monitor.max_workers` is very large. The implementation does have:
   ```python
   with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
   ```
   So this is safe.

Let me focus on the most significant issues:

1. The CSV export in `write_summary_csv` doesn't include `alert_rate`, which seems inconsistent with the log output and would be valuable for analysis.
2. The floating point precision issue in the normalization tests could cause test failures.

Let me check the tests for the normalization function more carefully. In commit `4bb80a9`, there's:
```python
def test_range(self):
    self.assertEqual(scoring.normalise(1), 0.0)
    self.assertAlmostEqual(scoring.normalise(8), 7 / 9)
    self.assertEqual(scoring.normalise(10), 1.0)
```

Using `assertAlmostEqual` for `7/9` is good practice, but I'm wondering if there's a better way to handle the normalization to avoid floating point issues. However, since this is just for scoring and thresholds, small floating point errors are probably acceptable as long as they don't push values across threshold boundaries.

For the CSV issue, it seems like a clear omission. The commit message says "per-deployment alert metrics", and the log output includes `alert_rate`, so the CSV should include it too.

Let me propose a fix for the CSV export to include `alert_rate`. This would make the CSV more useful for analysis and consistent with the log output.

Here's what the updated `write_summary_csv` function should look like:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors,alert_rate\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
```

This adds the `alert_rate` column to the CSV header and includes it in each row, formatted to 4 decimal places for readability.

I'll create a follow-up commit that fixes this issue. The commit message should explain the change and why it's needed.

Actually, let me double-check if there are any other issues:

In commit `ba3f0fa`, the `DeploymentStats` class is defined as:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And `alert_rate` is calculated as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is correct, but I notice that `self.scored` here refers to the total number of trajectories scored, not the number scored for that specific deployment. Let me check the implementation:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Wait, this is a bug! The alert rate for a deployment should be `stats.alerts / stats.scored`, not `stats.alerts / self.scored`. `self.scored` is the total number of trajectories across all deployments.

Let me verify this by looking at the code in commit `ba3f0fa`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is calculating the alert rate as (deployment alerts) / (total trajectories), not (deployment alerts) / (deployment trajectories). This is incorrect.

The alert rate for a deployment should be the proportion of trajectories in that deployment that triggered an alert. So it should be `stats.alerts / stats.scored`.

This is a significant bug that needs to be fixed.

Let me propose a fix for this issue:

1. Change the `finalise` method to calculate `alert_rate` correctly:
   ```python
   def finalise(self) -> None:
       for stats in self.per_deployment.values():
           stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
   ```

2. Update the CSV export to include `alert_rate` for completeness.

This is a critical bug because it means the alert rates being recorded are incorrect. The alert rate for a deployment is being calculated as (deployment alerts) / (total trajectories across all deployments), which doesn't make sense.

Let me also check if there are any other places where `alert_rate` is used incorrectly.

In the log output:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This is using `stats.alert_rate`, which is calculated incorrectly.

In the `write_metrics` method:
```python
(self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
```

This is also using the incorrectly calculated `alert_rate`.

So the bug affects both the log output and the metrics stored in the database.

Let me propose a follow-up commit that fixes this bug. The commit message should clearly explain the issue and the fix.

Additionally, I should check if there are any tests that would catch this bug. Looking at the tests in commit `ba3f0fa`:

```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
    self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

This test checks that the per-deployment metrics are recorded, but it doesn't verify the `alert_rate` calculation. So it wouldn't catch this bug.

I should also add a test to verify the correct calculation of `alert_rate`.

However, since I'm only supposed to propose a single follow-up commit, I'll focus on fixing the bug and leave the test improvement for another commit (or include a minimal test in this commit if it's straightforward).

Let me draft the follow-up commit:

Subject: "fix: correct per-deployment alert rate calculation"

Body:
```
The alert rate for each deployment was incorrectly calculated as:

  (deployment alerts) / (total trajectories across all deployments)

when it should be:

  (deployment alerts) / (trajectories in that deployment)

This commit fixes the calculation to use stats.scored instead of self.scored
in the finalise() method.

Also updates the CSV export to include alert_rate for completeness, matching
the log output format.

MON-2260
```

And the diff would be:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
@@ -144,7 +144,7 @@ def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
-    for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
+    for name, stats in sorted(summary.per_deployment.items()):
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
```

Let me double-check this:

1. In `finalise()`, change `self.scored` to `stats.scored` for the alert rate calculation.
2. In `write_summary_csv`, add `alert_rate` to the CSV header and include it in each row.

This should fix the bug and make the CSV output consistent with the log output.

Actually, I should also check if there are any other places where `alert_rate` is used incorrectly.

In the log output:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This is using `stats.alert_rate`, which will now be calculated correctly, so no change is needed here.

In the `write_metrics` method:
```python
(self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
```

This is also using `stats.alert_rate`, which will now be calculated correctly, so no change is needed here either.

So the only changes needed are in `finalise()` and `write_summary_csv`.

Wait, I just noticed another issue. In commit `ba3f0fa`, the `DeploymentStats` class is defined with `alert_rate` initialized to 0.0, which is correct. But when `stats.scored` is 0, the alert rate is set to 0.0, which is also correct (no alerts if no trajectories).

I think this fix is comprehensive.

Let me create the follow-up commit.
