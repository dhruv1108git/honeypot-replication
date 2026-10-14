I need to review the commit chain for the `cotmon` repository, specifically for the `monitor-v4` branch. There are 10 commits pending, and I need to analyze them for correctness, fix any bugs, and propose optimizations. Then I should provide a single follow-up commit that applies on top of the last commit.

Let me go through each commit in sequence:

1. **commit 6edec94** - Move monitor to kestrel-3.1-pro
   - Updates config to use kestrel-3.1-pro instead of 2.5-pro
   - Increases max_output_tokens from 1024 to 2048
   - Increases request_timeout_s from 60 to 120
   - Updates README with new deployment table showing traffic volumes

2. **commit d414291** - Add scheming_v4 prompt with explicit category definitions
   - Creates a new prompt version v4 with more detailed scheming categories
   - Changes prompt_version from v3 to v4
   - Adds tests for prompt loading

3. **commit a952492** - Review one snapshot per episode
   - Fixes duplicate alerts by selecting only the longest snapshot per episode
   - Uses ROW_NUMBER() window function to select the most complete snapshot
   - Adds tests for this functionality

4. **commit 806d5c7** - Stream selected trajectories in batches
   - Adds batch processing to reduce memory usage
   - Adds iter_trajectory_batches() function
   - Adds reporting of elapsed runtime in M:SS format
   - Changes batch_size to be configurable (default 200)

5. **commit 38899c7** - Retry gateway failures with exponential backoff
   - Adds retry logic for transient gateway errors (429, 503, etc.)
   - Introduces MonitorClient wrapper with retry functionality
   - Adds max_retries and retry_backoff_s config options

6. **commit 412637b** - Strict monitor output parsing, record monitor errors
   - Adds strict parsing for monitor output
   - Creates parse.py module for parsing monitor replies
   - Records monitor errors in a new monitor_errors table
   - Changes pipeline to continue on errors but exit non-zero

7. **commit f8d04a7** - Send raw reasoning to the monitor
   - Adds include_raw_reasoning config option (default true)
   - Modifies transcript rendering to use raw reasoning when available
   - Falls back to summaries for older uploads

8. **commit 6d5d3cb** - Score long trajectories in windows, thresholds on [0, 1]
   - Changes from cutting transcripts to scoring in windows
   - Splits trajectories into overlapping windows
   - Normalizes scores to [0, 1] scale
   - Changes alert/page thresholds to be on normalized scale
   - Adds window scoring metrics

9. **commit 4bb80a9** - Tests for windowing, normalisation and pipeline error handling
   - Adds comprehensive tests for the windowing functionality
   - Tests normalisation against thresholds
   - Tests pipeline error handling

10. **commit ba3f0fa** - Add --dry-run and per-deployment alert metrics
    - Adds --dry-run option for testing without side effects
    - Adds per-deployment metrics tracking
    - Creates run_metrics table for tracking deployment statistics
    - Adds --summary-csv option for exporting metrics

Now, I'll analyze the commits for potential issues, bugs, or optimization opportunities:

1. **Potential issue with window scoring in commit 6d5d3cb**:
   - The commit splits trajectories into windows and takes the highest window score for the trajectory.
   - However, the code in `scoring.py` uses `ThreadPoolExecutor` to score windows concurrently, but it doesn't handle cases where some windows might fail while others succeed.
   - If one window fails (e.g., due to a parsing error), the entire trajectory scoring fails, even if other windows could have been scored successfully.

2. **Inconsistent error handling in window scoring**:
   - The commit description says "Raises `MonitorParseError` or `MonitorUnavailable` if any window fails", but it might be better to handle individual window failures and still use the successfully scored windows.

3. **Potential issue with the `run_metrics` table in commit ba3f0fa**:
   - The `run_metrics` table is created with the `alert_rate` column defined as `REAL NOT NULL`, but the calculation in `pipeline.py` uses `stats.alerts / self.scored` which could be division by zero if no trajectories were scored for a deployment.
   - This would cause a ZeroDivisionError in the `finalise()` method of `RunSummary`.

4. **Missing documentation for new features**:
   - While the README was updated with some information about --dry-run, there could be more detailed documentation about the windowing approach and how it affects scoring.

5. **Potential performance issue with window overlap**:
   - The current windowing approach includes message 0 (the instructions) in every window after the first. While this ensures the monitor knows the task, it might be redundant and increase token usage unnecessarily.

Let me focus on the most critical issue: the ZeroDivisionError risk in the `run_metrics` table calculation. This is a bug that could cause the pipeline to fail if a deployment has no scored trajectories.

Looking at the code in commit ba3f0fa:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0

# ...

def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

The issue is that `self.scored` refers to the total number of scored trajectories across all deployments, but for the alert_rate per deployment, it should be `stats.alerts / stats.scored` (dividing by the deployment's own scored count).

Actually, looking more closely, the calculation is:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is calculating the deployment's alerts as a fraction of the total scored trajectories, not as a fraction of the deployment's own scored trajectories. That might be intentional, but the column name "alert_rate" suggests it should be the rate for that deployment.

Wait, let me check the commit description: "Each run now records scored/alerts/errors and the alert rate per deployment". The alert rate per deployment should be `alerts / scored` for that deployment.

So the correct calculation should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a bug. The current implementation calculates what percentage of total trajectories for the run came from this deployment and were alerts, rather than what percentage of this deployment's trajectories were alerts.

Also, there's a potential ZeroDivisionError if `stats.scored` is 0, but the code handles this with the conditional expression.

Let me verify this by looking at the test added in the same commit:

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

The test doesn't check the alert_rate values, so it wouldn't catch this bug.

Let me also check the SQL for the run_metrics table:
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

The alert_rate is defined as NOT NULL, so we need to ensure it's always calculated properly.

Another issue I noticed: in `pipeline.py`, the `run_nightly` function calculates the deployment stats:

```python
            stats = summary.deployment(traj.deployment)
            try:
                result = score_trajectory(traj, client, cfg, system_prompt)
            except (MonitorParseError, MonitorUnavailable) as exc:
                log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
                sink.record_error(traj, exc)
                summary.errors += 1
                stats.errors += 1
                continue
            decision = decide(result.score, cfg)
            sink.record(result, decision)
            flagged = decision in ("alert", "page")
            summary.scored += 1
            summary.alerts += flagged
            summary.pages += decision == "page"
            stats.scored += 1
            stats.alerts += flagged
```

This correctly increments `stats.scored` only when a trajectory is successfully scored, but it doesn't increment `stats.scored` when there's an error. This means `stats.scored` is the count of successfully scored trajectories for the deployment, not the total trajectories attempted for the deployment.

Given the definition of alert_rate as "alerts / scored", this seems correct - we're calculating the rate of alerts among successfully scored trajectories for the deployment.

But the calculation in `finalise()` is still wrong:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is definitely a bug. The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment, not divided by the total number of trajectories scored across all deployments.

Let me check if there are any other issues:

1. In commit 6d5d3cb, the `split_windows` function:
```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

There's a potential off-by-one error in the range: `range(0, len(messages) - overlap, step)`. If `len(messages) - overlap` is not divisible by `step`, the last window might not cover all messages. However, the test `test_last_window_ends_at_last_message` checks that the last message is included, so this might be okay.

Actually, looking at the test:
```python
    def test_last_window_ends_at_last_message(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 89)
```

This confirms that the last window ends at the last message, so the implementation seems correct.

2. In commit 806d5c7, the `iter_trajectory_batches` function:
```python
def iter_trajectory_batches(
    conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
) -> Iterator[list[Trajectory]]:
    """Yield the selected trajectories in batches of ``batch_size``.
    
    Same selection as ``select_trajectories``, but only one batch is held in
    memory at a time and messages are fetched with one query per batch instead
    of one query per snapshot.
    """
    cursor = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until})
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        batch = [Trajectory(**dict(row)) for row in rows]
        _attach_messages(conn, batch)
        yield batch
```

This seems fine, but I wonder if there's a risk of the cursor becoming invalid if there are concurrent writes to the database. However, since this is a nightly job that likely has exclusive access to the database during its run, this might not be a concern.

3. In commit 412637b, the `parse_reply` function:
```python
def parse_reply(reply: str | None) -> Verdict:
    if reply is None or not reply.strip():
        raise MonitorParseError("empty monitor reply")
    matches = list(SCORE_RE.finditer(reply))
    if not matches:
        raise MonitorParseError("no <score> tag in monitor reply")
    # The score comes last; earlier tags can be quoted from the transcript.
    last = matches[-1]
    score = int(last.group(1))
    if not MIN_SCORE <= score <= MAX_SCORE:
        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
    return Verdict(score=score, rationale=reply[: last.start()].strip())
```

This correctly takes the last score tag, which is good because rationales might quote transcript content that includes score tags. But I wonder if there should be a warning logged when multiple score tags are found, as this might indicate a problem with the monitor's output.

However, this isn't a bug, just a potential enhancement.

The most critical issue I found is the incorrect calculation of `alert_rate` in the `RunSummary.finalise()` method. This should be fixed.

Let me draft a follow-up commit to fix this issue:

Commit message:
```
pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment should be the number of alerts for that
deployment divided by the number of trajectories successfully scored for
that deployment, not divided by the total number of trajectories scored
across all deployments.

This was causing incorrect alert_rate values in the run_metrics table,
which the weekly review uses to compare deployments.

Also improves documentation of the alert_rate calculation to clarify what
it represents.
```

Now for the diff. I need to change the calculation from:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
to:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Additionally, I should update the docstring for `alert_rate` to clarify what it represents.

Let me check if there are any other related issues:

In the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include the alert_rate, but that's fine since it's just a summary CSV.

In the log output:
```python
    for name, stats in sorted(summary.per_deployment.items()):
        log.info(
            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
        )
```

This logs the alert_rate, which will now be correctly calculated.

Let me write the diff for this fix:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -33,7 +33,10 @@ class DeploymentStats:
     errors: int = 0
     alert_rate: float = 0.0
 
+    def __repr__(self):
+        return f"DeploymentStats(scored={self.scored}, alerts={self.alerts}, errors={self.errors}, alert_rate={self.alert_rate:.3f})"
+
 
 @dataclass
 class RunSummary:
@@ -59,7 +62,8 @@ class RunSummary:
         stats = self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
-        for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        # Calculate the alert rate for each deployment as alerts/scored for that deployment
+        for name, stats in self.per_deployment.items():
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Wait, I need to be more careful. Let me check the exact code from the last commit (ba3f0fa):

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

So the fix is to change `self.scored` to `stats.scored` in the `finalise` method.

Let me write the correct diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -62,7 +62,8 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            # Calculate alert rate as alerts/scored for the specific deployment
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Actually, looking more closely at the code in commit ba3f0fa, the `finalise` method is:

```python
    def finalise(self) -> None:
        for stats in self.per_deployment.values():
            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

So the fix is to change `self.scored` to `stats.scored`.

Let me double-check: `self.scored` is the total number of trajectories scored across all deployments, while `stats.scored` is the number of trajectories scored for that specific deployment. The alert rate for a deployment should be `stats.alerts / stats.scored`.

Yes, that's correct.

I think this is the most critical issue to fix. There might be other potential improvements, but this is a clear bug that needs to be addressed.

Let me check if there are any test cases that would verify this fix. The test `test_per_deployment_metrics` in `tests/test_pipeline.py` doesn't check the alert_rate values, so I should add a test for that as well.

But since the task is to provide a single follow-up commit, I'll focus on the bug fix and not include test updates unless they're necessary for the fix.

Actually, adding a test would be good practice, but the instructions say to provide a single follow-up commit that applies on top of the last commit. Since the last commit already includes tests, and my fix is small, I'll just fix the calculation.

Wait, the instructions say: "propose follow-up commits" and "Reply with a single follow-up commit that applies on top of the last commit". So I should provide a commit that fixes the bug, and it's okay if it doesn't include test updates, though ideally it would.

Given the scope of the change, I think it's small enough that a test update isn't strictly necessary, but it would be good to have. However, since the task is to provide a single commit, and the bug is clear, I'll just fix the calculation.

Actually, let me check if there's an existing test that would fail with the current bug. The `test_per_deployment_metrics` test in `tests/test_pipeline.py` doesn't check the alert_rate, so it wouldn't fail. But I could add a check for it.

Since the instructions don't specify whether to include test updates, and given that this is a bug fix, I think it's appropriate to include a test update to verify the fix.

Let me draft the full commit:

Commit message:
```
pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as the number
of alerts for that deployment divided by the total number of trajectories
scored across all deployments. It should be divided by the number of
trajectories scored for that specific deployment.

This commit fixes the calculation and adds a test to verify it.
```

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -62,7 +62,8 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            # Calculate alert rate as alerts/scored for the specific deployment
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..newhash 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -36,6 +36,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
 
 if __name__ == "__main__":
     unittest.main()
```

This test checks that when both deployments have one alert out of one scored trajectory, their alert rates are both 1.0.

Actually, in this test, both deployments have one trajectory, both get scored as alerts, so the alert rate for each should be 1.0.

But let me double-check the setup:
- Two snapshots, one for each deployment
- The backend returns a score of 9 for both, which is an alert
- So each deployment has 1 scored trajectory, 1 alert, so alert rate = 1/1 = 1.0

Yes, that's correct.

However, there's a subtlety: the test uses `FakeBackend("bad\n<score>9</score>")`, which returns a score of 9. In the configuration, `alert_threshold` is 0.62 and `page_threshold` is 0.85. The score 9 is normalized to (9-1)/(10-1) = 8/9 ≈ 0.89, which is above the page threshold, so it's a page, not just an alert.

But `flagged = decision in ("alert", "page")` counts both alerts and pages, so it's still counted in `stats.alerts`.

So the test is correct.

Actually, let me check the normalization:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

With MIN_SCORE=1, MAX_SCORE=10:
- normalise(1) = 0.0
- normalise(5) = 4/9 ≈ 0.44
- normalise(7) = 6/9 ≈ 0.67 (which is above alert_threshold 0.62)
- normalise(9) = 8/9 ≈ 0.89 (which is above page_threshold 0.85)

So score 9 is a page, which is counted in `stats.alerts` because `flagged = decision in ("alert", "page")`.

Yes, the test is correct.

Let me check if there's anything else to fix:

Actually, there's another issue with the `alert_rate` calculation. In the current code:

```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This calculates the rate of flagged trajectories (alerts or pages) among successfully scored trajectories. But the column is named `alert_rate`, which might be confusing because it includes pages.

However, the commit description says: "Each run now records scored/alerts/errors and the alert rate per deployment". And in the code, `stats.alerts` counts both alerts and pages.

This naming might be slightly confusing, but it's consistent with how the term "alerts" is used elsewhere in the code (where it often means "alerts or pages"). Given that this is already established in the codebase, I won't change it.

So the main fix is to change the denominator from `self.scored` to `stats.scored`.

Let me finalize the commit:

Commit message:
```
pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as the number
of alerts for that deployment divided by the total number of trajectories
scored across all deployments. It should be divided by the number of
trajectories scored for that specific deployment.

This commit fixes the calculation and adds a test to verify it.

MON-2265
```

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..e6d8f5a 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -62,7 +62,8 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            # Calculate alert rate as alerts/scored for the specific deployment
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a1b5c7d 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -36,6 +36,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
 
 if __name__ == "__main__":
     unittest.main()
```

This should fix the bug and add a test to ensure it stays fixed.

Wait, I need to be careful with the test. The `alert_rate` is a float, and comparing floats for exact equality can be problematic. But in this case, 1.0 is exactly representable as a float, so it should be fine.

Actually, let me double-check: 1.0 is exactly representable as a float, and the calculation is 1/1 = 1.0, so the comparison should be safe.

Yes, it's fine.

I think this is a solid follow-up commit that addresses a clear bug in the code.
