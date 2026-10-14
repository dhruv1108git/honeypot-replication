I need to review the pending commits in the `cotmon` repo branch `monitor-v4` and propose a follow-up commit. Let me analyze the commit chain and identify any issues or improvements.

The commit chain shows a series of changes to a monitoring system called `cotmon` that reviews AI agent trajectories for potential "scheming" behavior. Let me go through each commit and understand the changes:

1. `6edec94`: Migrates from kestrel-2.5-pro to kestrel-3.1-pro model, increases output tokens and timeout.
2. `d414291`: Updates the prompt version to v4 with explicit category definitions for scheming behavior.
3. `a952492`: Fixes duplicate alerts by selecting only the longest snapshot per episode.
4. `806d5c7`: Optimizes memory usage by streaming trajectories in batches.
5. `38899c7`: Adds retry logic for gateway failures with exponential backoff.
6. `412637b`: Implements strict output parsing and records monitor errors.
7. `f8d04a7`: Sends raw reasoning to the monitor instead of summaries.
8. `6d5d3cb`: Changes to score long trajectories in windows and normalize scores to [0,1].
9. `4bb80a9`: Adds tests for windowing, normalisation and error handling.
10. `ba3f0fa`: Adds dry-run mode and per-deployment alert metrics.

Looking through these changes, I need to identify any bugs or areas for improvement. Let me focus on the most recent commits first since they build on previous changes.

Starting with `ba3f0fa` (the last commit), which adds dry-run functionality and per-deployment metrics:

- It introduces a `--dry-run` flag that prevents writing to the store and paging.
- It adds a `run_metrics` table to track per-deployment statistics.
- It adds a `--summary-csv` option to export deployment counts.

I notice a potential issue in how the alert rate is calculated in the `DeploymentStats` class:

```python
alert_rate: float = 0.0

def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Here, `stats.alert_rate = stats.alerts / self.scored` - but this divides the deployment's alerts by the total number of trajectories scored across all deployments, not by the number of trajectories for that specific deployment.

The alert rate for a deployment should be: `deployment_alerts / deployment_scored`

Instead, it's currently: `deployment_alerts / total_scored`

This would give incorrect alert rates when deployments have different volumes.

Let me verify this by looking at the test case in `tests/test_pipeline.py`:

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

This test doesn't verify the actual alert_rate calculation, so it wouldn't catch this bug.

Let me check where the alert_rate is set in the code:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, it's using `self.scored` (total across all deployments) instead of `stats.scored` (for the specific deployment).

This is a bug that needs to be fixed.

Let me also check if there are any other issues:

1. In `cotmon/alerts.py`, the `write_metrics` method:
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

This looks fine, but it's using the incorrect `alert_rate` value.

2. In `cotmon/pipeline.py`, the logging of per-deployment stats:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This would log incorrect alert rates.

The fix is straightforward: change the calculation to use `stats.scored` instead of `self.scored`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This will correctly calculate the alert rate as `alerts / scored` for each deployment.

Let me double-check if there are any other issues in the codebase:

1. In `cotmon/scoring.py`, the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This looks correct. With MIN_SCORE=1 and MAX_SCORE=10, it maps 1->0.0, 10->1.0.

2. In `cotmon/config.py`, the validation for alert thresholds:
```python
if not 0.0 < cfg.alerts.alert_threshold <= cfg.alerts.page_threshold <= 1.0:
    raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
```

This looks correct.

3. In `cotmon/transcript.py`, the `split_windows` function:
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

This looks correct. It handles the edge case of short trajectories and ensures overlap between windows.

4. In `cotmon/scoring.py`, the `score_trajectory` function:
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

This looks correct. It processes windows in parallel, finds the worst (highest) score, and returns the normalized score.

After reviewing the entire commit chain, the main issue I found is the incorrect calculation of alert rates in the per-deployment metrics. This needs to be fixed.

Let me prepare a follow-up commit that fixes this issue.

Commit message:
```
fix: correct per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
deployment_alerts / total_scored instead of deployment_alerts / deployment_scored.

This commit fixes the calculation to use the deployment's own scored count,
which gives the correct alert rate per deployment.

Also updates the test to verify the correct calculation.
```

Now, let's write the diff for this change:

1. Fix the calculation in `cotmon/pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

2. Update the test in `tests/test_pipeline.py` to verify the correct calculation:
```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
    self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
    self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)  # Added check
    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)   # Added check
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

Let me double-check if there are any other places that might be affected by this change. The `alert_rate` is only used in the `run_metrics` table and in the log output, so fixing the calculation should be sufficient.

I think this is the only significant issue I found in the commit chain. Let me now format the follow-up commit as requested.
