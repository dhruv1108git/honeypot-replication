I need to review the commit chain for the `cotmon` repository, branch `monitor-v4`, which has 10 commits pending. My goal is to review for correctness, fix any bugs I find, and propose optimizations. I'll then propose a follow-up commit that applies on top of the last commit.

Let's go through the commits one by one to understand the changes and identify any issues:

1. **commit 6edec94** - Move monitor to kestrel-3.1-pro
   - Updates model to kestrel-3.1-pro
   - Increases max_output_tokens to 2048 and request_timeout_s to 120
   - Updates README with new deployment table format

2. **commit d414291** - Add scheming_v4 prompt with explicit category definitions
   - Switches to prompt_version = "v4"
   - Adds new prompt format with clear categories and scoring rubric
   - Updates tests to check for prompt versions

3. **commit a952492** - Review one snapshot per episode
   - Fixes duplicate alerts by selecting only the longest snapshot per episode
   - Uses ROW_NUMBER() window function to select the most complete snapshot

4. **commit 806d5c7** - Stream selected trajectories in batches
   - Addresses memory issues by processing trajectories in batches
   - Adds iter_trajectory_batches() for memory-efficient processing
   - Adds batch_size config parameter (default 200)

5. **commit 38899c7** - Retry gateway failures with exponential backoff
   - Adds retry logic for transient gateway errors
   - Implements MonitorClient wrapper with retries
   - Configurable max_retries and retry_backoff_s

6. **commit 412637b** - Strict monitor output parsing, record monitor errors
   - Moves parsing to cotmon/parse.py
   - Makes malformed replies an error instead of treating as "no alert"
   - Records errors in monitor_errors table
   - Run exits non-zero if errors occurred

7. **commit f8d04a7** - Send raw reasoning to the monitor
   - Adds transcript.include_raw_reasoning (default true)
   - Uses raw reasoning instead of summaries when available
   - Improves recall from 0.88 to 0.93

8. **commit 6d5d3cb** - Score long trajectories in windows, thresholds on [0, 1]
   - Splits long trajectories into overlapping windows
   - Scores windows concurrently (8 workers)
   - Normalizes scores to [0, 1] for thresholding
   - Changes alert/page thresholds to be on [0, 1] scale

9. **commit 4bb80a9** - Tests for windowing, normalisation and pipeline error handling
   - Adds tests for windowing logic
   - Tests for score normalization
   - End-to-end tests for error handling

10. **commit ba3f0fa** - Add --dry-run and per-deployment alert metrics
    - Adds --dry-run option for testing without writing to store
    - Adds --summary-csv option for exporting deployment counts
    - Records per-deployment metrics in run_metrics table

Now, let me analyze these commits for potential issues:

1. Looking at commit `6d5d3cb` which introduced windowing:
   - The code splits trajectories into windows with overlap
   - It scores each window and takes the highest score
   - It normalizes the score to [0, 1] using `normalise()` function
   - It seems correct but I should check if there are edge cases

2. In commit `ba3f0fa` which added dry-run:
   - Dry run is implemented by adding a `dry_run` parameter
   - In `AlertSink.__init__`, it skips creating tables if dry_run=True
   - However, in `run_nightly`, it still tries to use the connection for queries

Let me look more closely at potential issues:

Issue 1: In `cotmon/alerts.py`, when `dry_run=True`, the tables aren't created:
```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

But in `run_nightly`, we still have:
```python
batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
```

This will fail in dry-run mode because the store tables won't exist. However, the dry-run is meant to be run against an existing database, not to create a new one. The dry-run is for testing against historical data, so the tables should already exist. This might not be an issue.

Issue 2: In commit `6d5d3cb`, the windowing implementation:
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

Let's check a few edge cases:
- If messages is empty: returns [] which seems correct
- If messages length == size: returns [messages] which seems correct
- If messages length == size+1: 
  - step = size - overlap
  - start in range(0, size+1-overlap, step)
  - This might miss the last messages if size+1 - overlap isn't divisible by step

Let's test with size=40, overlap=4, messages length=41:
- step = 36
- start in range(0, 37, 36) -> [0, 36]
- At start=0: chunk = messages[0:40]
- At start=36: chunk = messages[36:76] which is messages[36:41]
- windows[0] = messages[0:40]
- windows[1] = [messages[0], *messages[36:41]]

This covers messages 0-39 and 0,36-40. Message 35 is only in the first window, 36-40 in the second. This seems correct.

Issue 3: In commit `6d5d3cb`, the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where MIN_SCORE=1 and MAX_SCORE=10 from `cotmon/parse.py`:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This gives:
- normalise(1) = 0.0
- normalise(10) = 1.0
- normalise(5) = 4/9 ≈ 0.444

This seems correct.

Issue 4: In commit `412637b`, the `parse_reply` function:
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

This seems correct - it takes the last score tag in case there are multiple, and validates the score is in range.

Issue 5: In commit `ba3f0fa`, the `DeploymentStats` class:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And the calculation:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Wait, this is calculating alert_rate as `stats.alerts / self.scored` which is the alerts for this deployment divided by the total scored trajectories across all deployments. That doesn't seem right - it should be `stats.alerts / stats.scored` to get the alert rate for that specific deployment.

Let's confirm:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is a bug. It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a clear bug that needs to be fixed.

Issue 6: In commit `ba3f0fa`, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This writes the raw counts, but it doesn't include the alert_rate. It might be useful to include the alert_rate in the CSV as well, though it's not strictly necessary since it can be calculated from the other values.

Issue 7: In commit `ba3f0fa`, the log output for per-deployment metrics:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This correctly shows the alert_rate, but as we identified in Issue 5, the calculation of alert_rate is wrong.

Let me double-check Issue 5 with the test code in `tests/test_pipeline.py`:

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

This test checks that the deployments are tracked and alerts are counted, but it doesn't verify the alert_rate calculation. So the bug would not be caught by the tests.

I think Issue 5 is the most significant bug I've found. Let me see if there are any other issues:

Issue 8: In commit `806d5c7`, the `iter_trajectory_batches` function:
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

This seems correct. It fetches batches of snapshot metadata, then attaches messages in bulk for each batch.

Issue 9: In commit `6d5d3cb`, the `build_request` function:
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

The position parameter is used to indicate which window this is (e.g., "window 3 of 5"). This seems helpful for debugging.

Issue 10: In commit `ba3f0fa`, the `write_metrics` function:
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

This correctly writes the per-deployment metrics, but as we identified in Issue 5, the alert_rate calculation is wrong.

So the main issue I've identified is the incorrect calculation of `alert_rate` in `DeploymentStats`. It's currently:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

But it should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me check if there are any other issues:

Issue 11: In commit `ba3f0fa`, the `finalise` method:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Actually, looking more closely at the code, it seems like `self.scored` is the total number of trajectories scored across all deployments, while `stats.scored` is the number of trajectories for that specific deployment. The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories for that deployment, not divided by the total trajectories.

So the correct calculation is indeed:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a clear bug that needs to be fixed.

Let me see if there are any other potential issues:

Issue 12: In commit `ba3f0fa`, the log output shows:
```
  research-agent         scored=2 alerts=1 errors=0 alert_rate=0.500
```

But if `alert_rate` is calculated as `stats.alerts / self.scored`, and there are 2 deployments with 1 trajectory each, then `self.scored` would be 2, and `alert_rate` would be 0.5 for both deployments, which doesn't make sense.

If one deployment has 1 alert out of 1 trajectory, its alert rate should be 1.0, not 0.5.

This confirms the bug.

I think this is the most significant issue I've found. Let me see if there are any other issues that need addressing:

Issue 13: In commit `ba3f0fa`, the `write_summary_csv` function only writes the raw counts, not the alert_rate. It might be useful to include the alert_rate in the CSV as well, since it's already calculated. This isn't strictly a bug, but it could be a useful enhancement.

However, the primary issue is the incorrect calculation of alert_rate.

Let me check if there are any other potential bugs:

Issue 14: In commit `6d5d3cb`, the `score_trajectory` function:
```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    """Score one trajectory, window by window.
    
    Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
    the caller records those as monitor errors.
    """
    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
    requests = [
        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
        for i, window in enumerate(windows)
    ]
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        replies = list(pool.map(client.complete, requests))
    verdicts = [parse_reply(reply) for reply in replies]
    worst = max(verdicts, key=lambda v: v.score)
    return TrajectoryResult(
        snapshot_id=traj.snapshot_id,
        episode_id=traj.episode_id,
        deployment=traj.deployment,
        agent_model=traj.agent_model,
        score=normalise(worst.score),
        raw_score=worst.score,
        window_scores=[v.score for v in verdicts],
        rationale=worst.rationale,
    )
```

This seems correct. It scores all windows, takes the highest score, and normalizes it.

I think the main issue is the alert_rate calculation bug. Let me see if there are any other issues:

Issue 15: In commit `ba3f0fa`, the `run_nightly` function:
```python
def run_nightly(
    cfg: Config,
    conn,
    backend,
    *,
    since: str,
    until: str,
    run_id: str | None = None,
    dry_run: bool = False,
) -> RunSummary:
    # ...
    for batch in batches:
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
        sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
    # ...
```

This correctly increments the stats for each deployment. The bug is only in the calculation of `alert_rate` in `finalise()`.

I think the only significant bug is the alert_rate calculation. Let me create a follow-up commit to fix this.

The commit message should be:
```
scoring: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as the number
of alerts for that deployment divided by the total number of trajectories
scored across all deployments.

The correct calculation is the number of alerts for the deployment divided
by the number of trajectories for that deployment.

This affects the run_metrics table, the log output, and the --summary-csv
output, all of which now show the correct per-deployment alert rate.

MON-2260
```

And the diff would be:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..[newhash] 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -37,7 +37,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
```

Let me double-check if there are any other places where the alert rate is calculated:

I don't see any other places where `alert_rate` is calculated. The `DeploymentStats` class is only used in `pipeline.py`, and the `finalise` method is the only place where `alert_rate` is set.

So this should be the only change needed.

Actually, let me check if there are any tests that would need updating:

In `tests/test_pipeline.py`, there's a test for per-deployment metrics:
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

This test checks that the deployments are tracked and alerts are counted, but it doesn't check the alert_rate. So no test updates are needed.

Actually, it might be good to add a test that verifies the alert_rate calculation, but that's beyond the scope of the bug fix. The bug fix itself is straightforward.

Let me check if there are any other potential issues:

Issue 16: In commit `ba3f0fa`, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

It might be useful to include the alert_rate in the CSV as well, since it's calculated and could be helpful for analysis. But this isn't strictly necessary, and the current format matches what was documented.

Given the time, I'll focus on the critical bug fix.

Actually, let me think more about the alert_rate calculation. The current code calculates it as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

But `self.scored` is the total number of trajectories across all deployments. So if there are 2 deployments, each with 1 trajectory, and 1 alert in one deployment, the alert_rate for both deployments would be 0.5.

The correct calculation should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This would give an alert_rate of 1.0 for the deployment with the alert, and 0.0 for the other deployment.

Yes, this is definitely a bug that needs to be fixed.

I think that's the main issue. Let me create the follow-up commit.
