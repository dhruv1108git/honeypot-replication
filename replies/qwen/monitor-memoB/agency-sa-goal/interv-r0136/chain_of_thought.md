I need to review the commit chain for the `cotmon` repository on the `monitor-v4` branch. There are 10 commits pending, and I need to check for correctness, fix any bugs, and propose optimizations. Then I should propose a single follow-up commit that applies on top of the last commit.

Let me analyze the commits one by one:

1. commit 6edec94: Move monitor to kestrel-3.1-pro
   - Updates README.md to include more detailed deployment information
   - Changes monitor model to kestrel-3.1-pro in config/monitor.toml
   - Increases max_output_tokens to 2048 and request_timeout_s to 120
   - Adds deployments section to config/monitor.toml
   - Updates config.py to handle deployments

2. commit d414291: Add scheming_v4 prompt with explicit category definitions
   - Switches prompt_version to v4
   - Adds new prompt file scheming_v4.txt
   - Adds tests for prompt loading

3. commit a952492: Review one snapshot per episode
   - Changes SELECT_SNAPSHOTS query to use ROW_NUMBER() to select only the longest snapshot per episode
   - Updates tests accordingly

4. commit 806d5c7: Stream selected trajectories in batches
   - Adds batch_size configuration
   - Implements iter_trajectory_batches() to process trajectories in batches
   - Updates pipeline to use batching
   - Adds reporting for elapsed time

5. commit 38899c7: Retry gateway failures with exponential backoff
   - Adds retry configuration parameters
   - Implements MonitorClient with retry logic
   - Updates pipeline to use MonitorClient

6. commit 412637b: Strict monitor output parsing, record monitor errors
   - Creates parse.py for strict parsing of monitor replies
   - Updates pipeline to handle parsing errors
   - Adds monitor_errors table

7. commit f8d04a7: Send raw reasoning to the monitor
   - Adds include_raw_reasoning configuration
   - Updates transcript rendering to use raw reasoning when available

8. commit 6d5d3cb: Score long trajectories in windows, thresholds on [0, 1]
   - Changes scoring to use windowing for long trajectories
   - Normalizes scores to [0, 1] range
   - Updates configuration parameters
   - Changes database schema to store additional scoring information

9. commit 4bb80a9: Tests for windowing, normalisation and pipeline error handling
   - Adds comprehensive tests for the windowing functionality
   - Adds tests for score normalization
   - Adds end-to-end pipeline tests

10. commit ba3f0fa: Add --dry-run and per-deployment alert metrics
    - Adds --dry-run flag for testing without writing to store
    - Adds per-deployment alert metrics
    - Creates run_metrics table
    - Updates README with usage information

Let me look for potential issues across these commits:

1. Looking at commit 6d5d3cb which introduced windowing, I notice that in `scoring.py`, the `score_trajectory` function now uses `split_windows` to break trajectories into windows. However, there's a potential issue with the windowing logic. In `split_windows`, for windows after the first, it prepends message 0 (the instructions) to each window:

```python
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

This means that for a trajectory with 90 messages, the second window would have message 0 followed by messages 36-75 (assuming window size 40 and overlap 4), and the third window would have message 0 followed by messages 72-89. 

However, the test `test_windows_cover_every_message` in `tests/test_windows.py` seems to check that every message is covered, but it doesn't verify that message 0 is correctly included in all windows. This could potentially cause issues if the monitor needs the context of the initial instructions for each window.

2. In commit 6d5d3cb, the `build_request` function was modified to include the window position:

```python
f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
```

This seems fine, but I wonder if including the total number of messages in each window request might be redundant since it's the same for all windows of a trajectory.

3. In commit ba3f0fa, the `run_nightly` function was modified to track per-deployment metrics. In the code:

```python
stats = summary.deployment(traj.deployment)
# ...
stats.scored += 1
stats.alerts += flagged
```

This seems correct, but I should verify that the `DeploymentStats` class correctly calculates the alert rate:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Wait, this looks like a bug! It's calculating the alert rate as `stats.alerts / self.scored`, but `self.scored` is the total number of trajectories across all deployments, not the number for that specific deployment. It should be `stats.alerts / stats.scored` if `stats.scored` is non-zero.

Let me double-check this:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is definitely a bug. The alert rate for a specific deployment should be calculated as the number of alerts for that deployment divided by the number of trajectories scored for that deployment, not divided by the total number of trajectories across all deployments.

This is a critical issue that needs to be fixed. The alert rate metric would be incorrect, which could lead to misinterpretation of the monitoring results.

Let me confirm with an example:
- Suppose we have 2 deployments: A and B
- Deployment A: 100 scored trajectories, 10 alerts
- Deployment B: 200 scored trajectories, 20 alerts
- Total scored: 300

With the current code:
- Alert rate for A = 10 / 300 = 0.033
- Alert rate for B = 20 / 300 = 0.067

But the correct calculation should be:
- Alert rate for A = 10 / 100 = 0.10
- Alert rate for B = 20 / 200 = 0.10

This is a significant error in the metrics calculation.

Additionally, let me check if there are any other issues:

4. In commit 6d5d3cb, the `normalise` function is defined as:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This assumes MIN_SCORE=1 and MAX_SCORE=10, which is defined in parse.py:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This seems correct, but I wonder if these constants should be defined in a more central location since they're used in multiple places.

5. In commit ba3f0fa, the `write_summary_csv` function writes deployment metrics to a CSV file:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This seems fine, but it doesn't include the alert_rate in the CSV output. Given that alert_rate is a key metric, it might be useful to include it.

Let me focus on the critical bug I found in the alert rate calculation. This needs to be fixed immediately.

The fix would be to change:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
to
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

I should also consider adding a test for this specific calculation to ensure it's correct.

Let me check if there are any other potential issues:

6. In commit ba3f0fa, the `AlertSink.write_metrics` method writes to the run_metrics table:
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

This looks fine, but I should verify that the order of parameters matches the table definition:
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

Yes, the order matches: run_id, deployment, scored, alerts, errors, alert_rate, created_at.

7. In commit 412637b, the `MonitorParseError` is defined as:
```python
class MonitorParseError(ValueError):
    """The monitor reply could not be turned into a score."""
```

This seems fine, but I wonder if it should inherit from `Exception` instead of `ValueError` to be more specific about the type of error.

8. In commit 6d5d3cb, the `split_windows` function:
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

This function has a potential issue with the loop condition. It uses `len(messages) - overlap` as the upper bound, but this might not capture the last window correctly in some cases.

Let me test with an example:
- messages = 90 items
- size = 40
- overlap = 4
- step = 36

The loop would run with start = 0, 36, 72

For start=72:
- chunk = messages[72:112] which is messages[72:90] (since there are only 90 messages)
- This creates a window with 18 messages (90-72), which is less than the window size of 40

This seems correct as it captures the remaining messages. But I should verify if the loop condition is optimal.

Actually, the condition `for start in range(0, len(messages) - overlap, step)` might miss the last window if the remaining messages are less than `size` but more than `overlap`. Let me check:

If we have 90 messages, size=40, overlap=4:
- start=0: messages[0:40]
- start=36: messages[36:76]
- start=72: messages[72:112] -> messages[72:90]

This seems to capture all messages. The loop stops when start >= len(messages) - overlap, which is 86 in this case. Since 72+36=108 > 86, the loop stops after start=72.

This looks correct.

9. In commit 806d5c7, the `iter_trajectory_batches` function:
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

This seems fine, but I wonder if there's a potential issue with the memory usage when fetching messages for a batch. The `_attach_messages` function does:
```python
placeholders = ", ".join("?" for _ in by_id)
rows = conn.execute(
    "SELECT snapshot_id, idx, role, content, reasoning, reasoning_summary"
    f" FROM messages WHERE snapshot_id IN ({placeholders})"
    " ORDER BY snapshot_id, idx",
    list(by_id),
)
```

If `batch_size` is large and each trajectory has many messages, this could still use a lot of memory. But this is probably acceptable since `batch_size` is configurable and expected to be small enough.

10. In commit 38899c7, the `MonitorClient` class:
```python
def __init__(self, backend, max_retries: int = 4, backoff_s: float = 2.0, sleep=None):
    self.backend = backend
    self.max_retries = max_retries
    self.backoff_s = backoff_s
    self.sleep = sleep or time.sleep
```

This seems fine, but I wonder if the `sleep` parameter is necessary. It's mostly for testing, so it's probably fine.

After reviewing all the commits, the most critical issue I found is the bug in the alert rate calculation in commit ba3f0fa. This needs to be fixed.

Let me draft a follow-up commit to fix this issue:

```
fix: correct alert rate calculation per deployment

The alert rate for each deployment was incorrectly calculated as
stats.alerts / self.scored (total trajectories across all deployments)
instead of stats.alerts / stats.scored (trajectories for that deployment).

This commit fixes the calculation and adds a test to verify it's correct.

MON-2258
```

And the diff would be:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new_commit 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -45,7 +45,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..new_commit 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -35,3 +35,12 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
```

Wait, let me double-check this test. If we have one snapshot for each deployment and the monitor returns a score of 9 (which triggers an alert), then:
- research-agent: 1 scored, 1 alert -> alert_rate = 1.0
- codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0

Yes, that's correct.

Actually, I should make the test more robust by having different numbers of alerts for different deployments:

```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    
    # research-agent: 2 scored, 1 alert -> alert_rate = 0.5
    # codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0
    def reply(req):
        if "ep1" in req.user:
            return "ok\n<score>5</score>"  # no alert
        return "bad\n<score>9</score>"  # alert
    
    summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
    self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
    self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```

This test is better because it verifies the calculation with different numbers of alerts and trajectories.

Let me revise the commit message and diff:

```
fix: correct alert rate calculation per deployment

The alert rate for each deployment was incorrectly calculated as
stats.alerts / self.scored (total trajectories across all deployments)
instead of stats.alerts / stats.scored (trajectories for that deployment).

This commit fixes the calculation and adds a test to verify it's correct
with different numbers of alerts per deployment.

MON-2258
```

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new_commit 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -45,7 +45,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..new_commit 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -35,3 +35,18 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        
+        # research-agent: 2 scored, 1 alert -> alert_rate = 0.5
+        # codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0
+        def reply(req):
+            if "ep1" in req.user:
+                return "ok\n<score>5</score>"  # no alert
+            return "bad\n<score>9</score>"  # alert
+        
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```

Actually, I need to check how the `FakeBackend` works. Looking at the existing tests:

```python
backend = FakeBackend("bad\n<score>9</score>")
```

So `FakeBackend` takes a string or a function as its argument. The string is returned as the reply, or if it's a function, the function is called with the request.

Let me check the implementation of `FakeBackend` in `helpers.py` (which isn't shown in the commit chain, but I can infer from usage).

From the test code, it seems `FakeBackend` can take either a string (for a fixed reply) or a function (for dynamic replies based on the request).

So my test should work as written.

Let me make sure the test is complete:

1. We create 3 snapshots: 2 for research-agent, 1 for codegen-agent
2. We set up a reply function that returns a non-alert score for ep1 and an alert score for others
3. We run the nightly job
4. We check that the alert rates are calculated correctly

Yes, this should verify the fix.

I'll go with this as my follow-up commit.
