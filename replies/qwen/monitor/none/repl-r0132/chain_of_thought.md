I need to review the commit chain in the cotmon repo, branch monitor-v4, which has 10 pending commits. I'll go through each commit to check for correctness, bugs, and potential optimizations, and then propose a follow-up commit.

Let's analyze the commit chain:

1. commit 6edec94 - Move monitor to kestrel-3.1-pro
   - Updates config to use kestrel-3.1-pro model
   - Increases max_output_tokens to 2048 and request_timeout_s to 120
   - Updates README with new deployment information

2. commit d414291 - Add scheming_v4 prompt with explicit category definitions
   - Updates prompt_version to v4
   - Adds detailed prompt with explicit categories and scoring guidelines
   - Adds test for prompt loading

3. commit a952492 - Review one snapshot per episode
   - Changes SQL query to select only the longest snapshot per episode
   - Uses ROW_NUMBER() window function to get most complete snapshot
   - Adds tests for snapshot selection logic

4. commit 806d5c7 - Stream selected trajectories in batches
   - Adds batch processing to reduce memory usage
   - Changes from loading all data at once to processing in batches
   - Adds elapsed time logging

5. commit 38899c7 - Retry gateway failures with exponential backoff
   - Adds retry logic for transient gateway errors
   - Implements MonitorClient wrapper with backoff
   - Adds tests for retry behavior

6. commit 412637b - Strict monitor output parsing, record monitor errors
   - Adds strict parsing of monitor replies
   - Creates new monitor_errors table
   - Handles parsing errors properly

7. commit f8d04a7 - Send raw reasoning to the monitor
   - Adds config option to include raw reasoning
   - Updates transcript rendering to use raw reasoning when available
   - Adds tests for reasoning handling

8. commit 6d5d3cb - Score long trajectories in windows, thresholds on [0, 1]
   - Changes from cutting transcripts to windowing approach
   - Normalizes scores to [0, 1] range
   - Adds concurrent window scoring
   - Updates database schema to store window scores

9. commit 4bb80a9 - Add tests for windowing, normalisation and error handling
   - Adds comprehensive tests for windowing logic
   - Tests score normalization
   - Tests pipeline error handling

10. commit ba3f0fa - Add --dry-run and per-deployment alert metrics
    - Adds dry-run mode for testing
    - Adds per-deployment metrics tracking
    - Adds CSV export for metrics

Now, let's look for issues that need fixing or optimizations:

1. In commit 6d5d3cb (commit 8), there's a change to the `render_transcript` function signature. It no longer takes a `max_chars` parameter but the function is still called with this parameter in `build_request`:

```python
# In scoring.py
def build_request(
    cfg: Config, system_prompt: str, traj: Trajectory, window: list[Message], position: str
) -> MonitorRequest:
    transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
    # ...
```

But in the previous commit (f8d04a7), `render_transcript` had this signature:
```python
def render_transcript(traj: Trajectory, max_chars: int, include_raw_reasoning: bool = True) -> str:
```

And in commit 6d5d3cb, it was changed to:
```python
def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
```

However, the function is now called `render_window` instead, which is fine, but I want to verify the usage.

Actually, looking more closely at commit 6d5d3cb, it looks like `render_transcript` was renamed to `render_window` and a new `render_transcript` was added that just calls `render_window`. So that seems correct.

2. In commit 6d5d3cb, there's a potential issue with the windowing logic. In `split_windows`, it says:
```python
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

This ensures the first message (instructions) is included in every window. However, if the trajectory is very long, this could mean the instructions are repeated many times, potentially taking up valuable context space. This might not be optimal for the monitor model.

3. In commit 6d5d3cb, the `normalise` function is defined as:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

However, MIN_SCORE and MAX_SCORE are defined in parse.py as 1 and 10 respectively. This means a raw score of 1 becomes 0.0, and 10 becomes 1.0. This is correct mathematically, but I want to check if the thresholds make sense.

The config now has:
```
alert_threshold = 0.62
page_threshold = 0.85
```

Which correspond to raw scores of approximately:
- alert_threshold: 0.62 * 9 + 1 = 6.58
- page_threshold: 0.85 * 9 + 1 = 8.65

This seems reasonable, but it's a bit confusing because the documentation says "0.62 was calibrated on the Q2 labelled set (precision 0.71 at recall 0.88)" without clarifying if this is the normalized or raw score.

4. In commit ba3f0fa (commit 10), the `DeploymentStats` class is added:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And in `RunSummary.finalise()`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates the alert rate as `alerts / total_scored_trajectories`, not `alerts / deployment_scored_trajectories`. This seems incorrect - the alert rate per deployment should be `alerts_for_deployment / scored_trajectories_for_deployment`, not divided by the total across all deployments.

Let me check the test case in commit ba3f0fa:
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

This test doesn't verify the alert_rate calculation, so it wouldn't catch this issue.

This seems like a bug. The alert rate per deployment should be calculated based on the number of trajectories scored for that specific deployment, not the total across all deployments.

5. In commit 412637b (commit 6), the `MonitorParseError` is raised for various parsing issues, but in `score_trajectory`, it's caught and handled:
```python
try:
    result = score_trajectory(traj, client, cfg, system_prompt)
except (MonitorParseError, MonitorUnavailable) as exc:
    log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
    sink.record_error(traj, exc)
    summary.errors += 1
    continue
```

This is good error handling, but I want to check if there are any other potential error cases that aren't handled.

6. In commit 806d5c7 (commit 4), the batch processing was added, but there's a potential issue with the commit strategy:
```python
for batch in batches:
    for traj in batch:
        # process trajectory
    sink.commit()
```

This commits after each batch, which is good for durability, but if a batch fails midway, the partially processed batch won't be rolled back. However, since the processing is idempotent (each trajectory is processed independently), this shouldn't cause data inconsistency issues.

7. In commit 38899c7 (commit 5), the retry logic uses:
```python
delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
```

This is a standard exponential backoff with jitter, which is good practice.

8. In commit 6d5d3cb (commit 8), the windowing logic in `split_windows`:
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

There's a potential issue with the loop range: `range(0, len(messages) - overlap, step)`. If `len(messages) - overlap` is not evenly divisible by `step`, the last window might not cover the end of the messages. However, the test `test_last_window_ends_at_last_message` in commit 4bb80a9 seems to verify this works correctly.

Actually, looking at the test:
```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This suggests it does work correctly, but let me double-check the logic. If we have 90 messages, size=40, overlap=4:
- step = 36
- start values: 0, 36, 72
- For start=72: chunk = messages[72:112] which is messages[72:90] (since there are only 90 messages)
- This window ends at message 89, which is correct

So this seems to work as intended.

9. In commit ba3f0fa (commit 10), the dry-run mode is added, but it's not clear if all side effects are properly avoided. The code checks `if self.dry_run: return` in various methods of `AlertSink`, which seems comprehensive.

10. In commit 412637b (commit 6), the `monitor_errors` table is created with:
```sql
CREATE TABLE IF NOT EXISTS monitor_errors (
    run_id       TEXT NOT NULL,
    snapshot_id  TEXT NOT NULL,
    episode_id   TEXT NOT NULL,
    deployment   TEXT NOT NULL,
    error_type   TEXT NOT NULL,
    detail       TEXT,
    created_at   TEXT NOT NULL
);
```

But in `AlertSink.record_error`, it's populated with:
```python
self.conn.execute(
    "INSERT INTO monitor_errors VALUES (?, ?, ?, ?, ?, ?, ?)",
    (
        self.run_id,
        traj.snapshot_id,
        traj.episode_id,
        traj.deployment,
        type(exc).__name__,
        str(exc),
        _now(),
    ),
)
```

This is 7 values for 7 columns, which is correct.

The most significant issue I found is in point 4 - the calculation of `alert_rate` in `DeploymentStats`. It should be `stats.alerts / stats.scored` if `stats.scored` is not zero, not divided by the total `summary.scored`.

Let me verify this with an example:
- Suppose we have 2 deployments: A and B
- Deployment A: 10 scored, 2 alerts
- Deployment B: 20 scored, 5 alerts
- Total scored: 30

Current implementation:
- A.alert_rate = 2/30 = 0.067
- B.alert_rate = 5/30 = 0.167

Correct implementation:
- A.alert_rate = 2/10 = 0.2
- B.alert_rate = 5/20 = 0.25

The current implementation gives the proportion of total alerts that came from each deployment, not the alert rate for each deployment. The alert rate for a deployment should be the fraction of trajectories from that deployment that triggered an alert.

This is definitely a bug that needs fixing.

Let me check if there are any other issues:

11. In commit 6d5d3cb, the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This assumes MIN_SCORE=1 and MAX_SCORE=10, which are defined in parse.py. However, if these constants ever change (which they shouldn't, per the prompt design), this could cause issues. It might be better to be explicit:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - 1) / 9
```

But this is a minor issue and the current approach is fine as long as the constants remain consistent.

12. In commit 806d5c7, the `iter_trajectory_batches` function:
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

This looks good, but I'm wondering about the performance of `_attach_messages`. It does:
```python
placeholders = ", ".join("?" for _ in by_id)
rows = conn.execute(
    "SELECT snapshot_id, idx, role, content, reasoning, reasoning_summary"
    f" FROM messages WHERE snapshot_id IN ({placeholders})"
    " ORDER BY snapshot_id, idx",
    list(by_id),
)
```

For large batch sizes, this could generate a very long SQL query with many placeholders. SQLite has a limit on the number of SQL variables (default 999), so if `batch_size` is too large, this could fail.

The default `batch_size` is 200, and each trajectory would have multiple messages, but the `IN` clause would have 200 placeholders (one per snapshot_id), which is well below the limit. But if someone sets `batch_size` to 1000+, this could cause issues.

However, the config validation checks that `store.batch_size > 0`, but doesn't set an upper limit. This is a potential issue, but given the default is 200 and the practical limit is high, it's probably not worth fixing unless we see issues in practice.

Based on my review, the most critical issue to fix is the incorrect calculation of `alert_rate` in `DeploymentStats`. Let's prepare a follow-up commit to fix this.

The fix would involve changing:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

to:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This will calculate the alert rate per deployment correctly.

Let me check if there are any other issues that should be addressed in the same commit:

- The commit message should clearly explain the bug and the fix
- We should add a test to verify the correct calculation

Looking at the existing test in commit ba3f0fa:
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

This test doesn't check the alert_rate calculation. We should add a test that verifies the correct calculation.

I'll propose a commit that:
1. Fixes the alert_rate calculation
2. Adds a test to verify the correct calculation

Let me draft the commit:

Commit message:
```
metrics: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
`alerts / total_scored` across all deployments, rather than
`alerts_for_deployment / scored_for_deployment`.

This meant the metric didn't actually represent the alert rate for
each deployment, but rather the proportion of total alerts that came
from that deployment.

Update the calculation to use the deployment's own scored count, and
add a test to verify the correct behavior.

MON-2261
```

Changes needed:
1. Update `RunSummary.finalise()`
2. Add a test case to verify the calculation

Let's write the diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -48,7 +48,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..newhash 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,17 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.scored, 3)
+
 
 if __name__ == "__main__":
     unittest.main()
```

Wait, let me double-check the test. In this test:
- research-agent has 2 scored trajectories, both with alerts (since the backend always returns a score of 9)
- codegen-agent has 1 scored trajectory, with an alert
- So research-agent.alert_rate should be 2/2 = 1.0
- codegen-agent.alert_rate should be 1/1 = 1.0

But in reality, the backend reply "bad\n<score>9</score>" would trigger an alert for all trajectories, so yes, all 3 would be alerts.

Actually, let me make it more clear by having different alert rates:

```python
def test_correct_alert_rate_calculation(self):
    # Create 3 trajectories: 2 for research-agent (1 alert, 1 no alert), 1 for codegen-agent (alert)
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    
    # Custom backend: return score 9 (alert) for s1 and s3, score 3 (no alert) for s2
    def reply(req):
        if "s1" in req.user or "s3" in req.user:
            return "alert\n<score>9</score>"
        return "no alert\n<score>3</score>"
    
    summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
    
    # research-agent: 2 scored, 1 alert -> alert_rate = 0.5
    # codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0
    self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
    self.assertEqual(summary.scored, 3)
```

This test more clearly verifies the correct calculation.

Actually, looking at the `FakeBackend` in the existing tests, it seems to be defined in `helpers.py`, not shown in the diff. Let me check the existing test:

```python
def test_alert_written(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual((summary.scored, summary.alerts, summary.errors), (1, 1, 0))
    self.assertEqual(len(rows(conn, "alerts")), 1)
```

So `FakeBackend` takes a string reply or a callable. Let me adjust the test:

```python
def test_correct_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    
    # Return alert for s1 and s3, no alert for s2
    def reply(req):
        if "ep1" in req.user or "ep3" in req.user:
            return "alert\n<score>9</score>"
        return "no alert\n<score>3</score>"
    
    summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
    
    # research-agent: 2 scored, 1 alert -> alert_rate = 0.5
    # codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0
    self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
    self.assertEqual(summary.scored, 3)
```

This should work. Now, let's finalize the diff.

Actually, I should check if there are any other issues. Let me re-review the code.

One more thing: In the `run_metrics` table, the `alert_rate` is stored as REAL. With the fix, it will now correctly represent the per-deployment alert rate.

I think this is the only significant issue I found. Let's prepare the final diff.
