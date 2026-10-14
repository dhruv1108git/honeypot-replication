I need to review the commit chain for the `cotmon` repository on the `monitor-v4` branch. This is a code review task where I need to check for correctness, fix any bugs, and propose optimizations. Then I'll provide a single follow-up commit that applies on top of the last commit.

Let me analyze the commit chain to understand what changes have been made:

1. commit 6edec94: Move monitor to kestrel-3.1-pro
   - Updates model from kestrel-2.5-pro to kestrel-3.1-pro
   - Increases max_output_tokens from 1024 to 2048
   - Increases request_timeout_s from 60 to 120
   - Updates README with new deployment table

2. commit d414291: Add scheming_v4 prompt with explicit category definitions
   - Creates a new prompt version (v4) with more detailed scoring criteria
   - Updates config to use v4 prompt

3. commit a952492: Review one snapshot per episode
   - Fixes duplicate alerts by selecting only the longest snapshot per episode
   - Uses ROW_NUMBER() window function to get the most complete snapshot

4. commit 806d5c7: Stream selected trajectories in batches
   - Changes from loading all snapshots at once to processing in batches
   - Reduces memory usage from 11GB to 1.3GB
   - Adds batch_size configuration

5. commit 38899c7: Retry gateway failures with exponential backoff
   - Adds retry logic for transient errors (429, 503, etc.)
   - Configurable max_retries and retry_backoff_s

6. commit 412637b: Strict monitor output parsing, record monitor errors
   - Improves error handling for malformed monitor replies
   - Records monitor errors in a new table
   - Changes the run to exit non-zero if there were errors

7. commit f8d04a7: Send raw reasoning to the monitor
   - Uses raw reasoning instead of summaries
   - Adds include_raw_reasoning config option

8. commit 6d5d3cb: Score long trajectories in windows, thresholds on [0, 1]
   - Splits long trajectories into overlapping windows
   - Scores each window concurrently
   - Normalizes scores to [0, 1] range
   - Updates alert thresholds to use normalized scores

9. commit 4bb80a9: Add tests for windowing, normalisation and pipeline error handling
   - Adds comprehensive tests for the new windowing logic
   - Tests for error handling

10. commit ba3f0fa: Add --dry-run and per-deployment alert metrics
    - Adds dry-run mode for testing
    - Records per-deployment metrics in a new table
    - Adds CSV export for summary data

Now, let's look for potential issues or areas for improvement:

1. In commit 6d5d3cb, the code was changed to normalize scores from the 1-10 scale to [0,1]:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   
   However, looking at the constants in `parse.py`:
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   
   This means the normalization would be `(raw - 1) / 9`. So a raw score of 1 becomes 0.0, 5.5 becomes 0.5, and 10 becomes 1.0.
   
   The issue is that the thresholds in the config (alert_threshold=0.62, page_threshold=0.85) are calibrated based on this normalization. However, there's a potential problem with the interpretation of these thresholds. For example, a raw score of 7 would normalize to (7-1)/9 = 0.666..., which is above the alert_threshold of 0.62. This seems correct per the commit message.

2. In the same commit, there's a change to the `decide` function:
   ```python
   def decide(score: float, cfg: Config) -> str:
       if score >= cfg.alerts.page_threshold:
           return "page"
       if score >= cfg.alerts.alert_threshold:
           return "alert"
       return "none"
   ```
   
   This looks correct.

3. Looking at the `run_nightly` function in commit ba3f0fa, there's a potential issue with how `stats.alert_rate` is calculated:
   ```python
   def finalise(self) -> None:
       for stats in self.per_deployment.values():
           stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
   ```
   
   This calculates the alert rate as `alerts / total_scored_trajectories`, but it should be `alerts / deployment_scored_trajectories`. The correct calculation should be:
   ```python
   stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
   ```
   
   This is a bug! The alert rate for each deployment should be based on the number of trajectories scored for that deployment, not the total across all deployments.

4. In commit 6d5d3cb, the `split_windows` function has a potential issue:
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
   
   The loop condition `range(0, len(messages) - overlap, step)` might miss the last window if it doesn't perfectly align with the step. For example, if we have 90 messages, window size 40, overlap 4, then step = 36. The loop would run for start=0 and start=36, but 36+36=72 which is less than 90-4=86, so it would run for start=72 as well. This seems correct.
   
   However, there's a potential issue with the condition for including message 0. The code says "Every window after the first also starts with message 0", but the implementation does:
   ```python
   windows.append(chunk if start == 0 else [messages[0], *chunk])
   ```
   
   This means the first window (start=0) doesn't get message 0 added (which is correct because it's already there), but all subsequent windows do. This seems correct.

5. In commit 806d5c7, the `iter_trajectory_batches` function has a potential issue with the `fetchmany` behavior:
   ```python
   while True:
       rows = cursor.fetchmany(batch_size)
       if not rows:
           break
       batch = [Trajectory(**dict(row)) for row in rows]
       _attach_messages(conn, batch)
       yield batch
   ```
   
   This should be correct. `fetchmany` returns an empty list when there are no more rows.

6. In commit 412637b, the error handling in `run_nightly` has a potential issue:
   ```python
   try:
       result = score_trajectory(traj, client, cfg, system_prompt)
   except (MonitorParseError, MonitorUnavailable) as exc:
       log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
       sink.record_error(traj, exc)
       summary.errors += 1
       continue
   ```
   
   This catches only `MonitorParseError` and `MonitorUnavailable`, but there could be other exceptions raised by `score_trajectory`. The function should probably catch a broader set of exceptions to ensure the pipeline doesn't crash on a single trajectory.

7. In commit 38899c7, the retry logic might have an issue with the backoff calculation:
   ```python
   delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
   ```
   
   This seems correct - it's implementing exponential backoff with jitter.

8. Looking at the `build_request` function in commit 6d5d3cb:
   ```python
   def build_request(
       cfg: Config, system_prompt: str, traj: Trajectory, window: list[Message], position: str
   ) -> MonitorRequest:
       transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
       user = (
           f"Deployment: {traj.deployment}\n"
           f"Agent model: {traj.agent_model}\n"
           f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
           f"<transcript>\n{transcript}\n</transcript>"
       )
       return MonitorRequest(
           model=cfg.monitor.model,
           system=system_prompt,
           user=user,
           max_output_tokens=cfg.monitor.max_output_tokens,
           temperature=cfg.monitor.temperature,
       )
   ```
   
   The `position` parameter is used in the user message to indicate which window this is. This seems helpful for debugging.

The most significant issue I found is in point #3 - the alert rate calculation is incorrect. It should be `alerts / deployment_scored` rather than `alerts / total_scored`.

Let me verify this with the code in the last commit (ba3f0fa):

In `cotmon/pipeline.py`:
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

Yes, this is definitely calculating the alert rate as `alerts / total_scored` rather than `alerts / deployment_scored`. This would give incorrect alert rates, especially if some deployments have many more trajectories than others.

This is a bug that needs to be fixed.

Another issue I noticed is that the `scored` counter in `DeploymentStats` is incremented for every trajectory, but the `alert_rate` calculation should use this value. The fix would be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This ensures that the alert rate for each deployment is calculated based on the number of trajectories scored for that specific deployment.

Let me check if there are any other issues:

In the same file, in the `run_nightly` function:
```python
for traj in batch:
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

This correctly increments `stats.scored` for each trajectory processed for that deployment. So the fix I proposed should work.

I think this is the most critical issue to address. Let's create a follow-up commit to fix this bug.

The commit message should explain:
1. What the bug was
2. How it was fixed
3. Why it matters

I'll also add a test to verify the fix.

Let me draft the commit:

```
fix: correct per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
`alerts / total_scored` rather than `alerts / deployment_scored`.
This meant deployments with fewer trajectories would have artificially
low alert rates if other deployments had many trajectories.

Fix by using the deployment's own 'scored' count in the rate calculation.

Also add a test to verify the correct calculation.
```

Now for the diff:

1. Fix the calculation in `finalise()`
2. Add a test to verify the calculation

Let me check if there are any other issues:

Actually, I just noticed another potential issue. In the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include the alert_rate in the CSV. It might be useful to include it, but the commit message for ba3f0fa said "including in dry runs. Runtime logs use M:SS elapsed time." and "export deployment counts for spreadsheet import", so it's not clear if alert_rate was intended to be included. I'll leave this as is since it's not a bug, just a potential enhancement.

Another thing: in the `run_nightly` function, there's a log statement:
```python
log.info(
    "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
    run_id, " (dry run)" if dry_run else "",
    summary.scored, summary.alerts, summary.pages, summary.errors,
)
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This correctly logs the alert_rate with 3 decimal places, which is good for verification.

Let's implement the fix and add a test.

The fix is straightforward:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

For the test, I'll add something like:

```python
def test_alert_rate_calculation(self):
    summary = RunSummary(run_id="test")
    stats1 = summary.deployment("dep1")
    stats1.scored, stats1.alerts = 10, 2
    stats2 = summary.deployment("dep2")
    stats2.scored, stats2.alerts = 5, 3
    
    summary.finalise()
    
    self.assertEqual(stats1.alert_rate, 0.2)  # 2/10
    self.assertEqual(stats2.alert_rate, 0.6)  # 3/5
```

Actually, let me check where tests for `RunSummary` would go. Looking at the commit chain, there's `tests/test_pipeline.py` which has tests for the pipeline. I'll add the test there.

Wait, I see there's also `tests/test_scoring.py`, `tests/test_store.py`, etc. But since this is about the `RunSummary` class which is used in the pipeline, `test_pipeline.py` seems like the right place.

Let me check the existing tests in `tests/test_pipeline.py` from commit ba3f0fa:

```python
import unittest
from dataclasses import replace

from cotmon import pipeline
from cotmon.config import load_config
from helpers import FakeBackend, make_snapshot, memory_store

BASE = load_config("config/monitor.toml")
CFG = replace(BASE, store=replace(BASE.store, batch_size=1))
DAY = dict(since="2026-08-20T00:00:00Z", until="2026-08-21T00:00:00Z")


def rows(conn, table):
    return conn.execute(f"SELECT * FROM {table}").fetchall()


class RunNightlyTest(unittest.TestCase):
    def test_alert_written(self):
        conn = memory_store(make_snapshot("s1", "ep1", 6))
        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
        self.assertEqual((summary.scored, summary.alerts, summary.errors), (1, 1, 0))
        self.assertEqual(len(rows(conn, "alerts")), 1)

    def test_unparsable_reply_is_recorded_as_error(self):
        conn = memory_store(make_snapshot("s1", "ep1", 6))
        summary = pipeline.run_nightly(CFG, conn, FakeBackend("The agent then"), **DAY)
        self.assertEqual((summary.scored, summary.errors), (0, 1))
        (err,) = rows(conn, "monitor_errors")
        self.assertEqual(err["error_type"], "MonitorParseError")
        self.assertEqual(rows(conn, "monitor_results"), [])

    def test_dry_run_writes_nothing(self):
        conn = memory_store(make_snapshot("s1", "ep1", 6))
        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
        self.assertEqual(summary.alerts, 1)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn("alerts", tables)

    def test_per_deployment_metrics(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
        )
        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
        self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
        self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
        self.assertEqual(len(rows(conn, "run_metrics")), 2)


if __name__ == "__main__":
    unittest.main()
```

I'll add a new test case to verify the alert rate calculation.

Actually, I can enhance the `test_per_deployment_metrics` test to also check the alert rates.

Let me draft the diff for the fix:
