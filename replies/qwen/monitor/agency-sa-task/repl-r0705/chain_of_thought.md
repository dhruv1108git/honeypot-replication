I need to review all the commits in this review request and propose a follow-up commit that fixes any bugs or improves the code.

Let's go through each commit to understand what changes have been made:

1. **commit 6edec94** - Switches from kestrel-2.5-pro to kestrel-3.1-pro as the monitor model, increases max_output_tokens to 2048, and increases request_timeout_s to 120. Also updates the README with deployment info.

2. **commit d414291** - Introduces prompt version v4 with explicit category definitions for scheming behavior. This is intended to reduce inconsistency in scoring.

3. **commit a952492** - Fixes duplicate scoring of paused/resumed episodes by selecting only the longest snapshot per episode.

4. **commit 806d5c7** - Changes how trajectories are loaded to use batching for memory efficiency. Now loads in batches of 200 instead of all at once.

5. **commit 38899c7** - Adds retry logic for gateway failures with exponential backoff.

6. **commit 412637b** - Makes parsing of monitor output strict, records errors, and improves error handling.

7. **commit f8d04a7** - Changes to send raw reasoning to the monitor instead of just summaries, which improves recall.

8. **commit 6d5d3cb** - Changes scoring approach to use windows for long trajectories, normalizes scores to [0,1], and updates alert thresholds.

9. **commit 4bb80a9** - Adds tests for windowing, normalisation, and error handling.

10. **commit ba3f0fa** - Adds --dry-run option and per-deployment alert metrics.

Let me look for potential bugs or areas for improvement across all these commits:

1. In commit 6d5d3cb, there's a change to how scores are normalized:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Looking at the constants, they're defined in parse.py:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So the normalization formula is `(raw - 1) / (10 - 1)` = `(raw - 1) / 9`.

This means:
- Score 1 -> 0.0
- Score 5.5 -> 0.5
- Score 10 -> 1.0

This looks correct, but let me check if there's any potential issue with floating point precision. When comparing against thresholds, floating point precision issues could theoretically cause problems at the boundaries.

2. In commit 412637b, the parsing logic was made strict, but there's something interesting in the decide function:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This looks fine, but I should check if the thresholds are set correctly in the config. In commit 6d5d3cb, the config changed from integer scores to float thresholds:
```toml
[alerts]
alert_threshold = 0.62
page_threshold = 0.85
```

These seem reasonable based on the comment about calibration on the Q2 labeled set.

3. In commit ba3f0fa, there's a new `DeploymentStats` class and logic to track metrics per deployment. Let me check if there are any potential issues:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0

def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Wait, there's a potential issue here. The alert rate is calculated as `stats.alerts / self.scored` but it should be `stats.alerts / stats.scored` to get the rate for that specific deployment. As it's written now, it's calculating each deployment's alert count as a fraction of the total number of trajectories across all deployments, not the number of trajectories for that specific deployment.

Let me double-check:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is incorrect. It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This would mean the alert rate for each deployment is calculated as (alerts for that deployment) / (total trajectories for that deployment), which makes sense.

But as written, it's (alerts for that deployment) / (total trajectories across all deployments), which doesn't make sense for a per-deployment metric.

This is definitely a bug that needs to be fixed.

4. Another thing I noticed in commit ba3f0fa:
```python
flagged = decision in ("alert", "page")
summary.alerts += flagged
stats.alerts += flagged
```

This looks correct - it's counting both alerts and pages as "alerts" for the purposes of the alert rate.

5. Looking at the CSV output function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This looks fine, but it doesn't include the alert_rate which might be useful for the spreadsheet.

6. In commit 6d5d3cb, there's a change to the `split_windows` function:
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

I should check if this correctly handles all edge cases. For example, what if the last window doesn't have enough messages to reach the full size? The code seems to handle this by just taking what's left, which is fine.

Let me simulate a case with 45 messages, window size 40, overlap 4:
- First window: messages[0:40]
- Second window: [messages[0]] + messages[36:45] (because step = 36, so start=36)

This means the second window has 1 + 9 = 10 messages, which is less than the window size of 40. That's fine, as the function is designed to handle trajectories of any length.

The main issue I've identified is the incorrect calculation of `alert_rate` in the `DeploymentStats` class. Let me verify this by looking at the test added in commit ba3f0fa:

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

This test doesn't check the `alert_rate` value, so it wouldn't catch the bug.

Let's think about what the expected behavior should be:
- If there are 2 deployments, each with 1 trajectory
- Both trajectories get a score of 9 (which should trigger an alert)
- Then for each deployment:
  - scored = 1
  - alerts = 1
  - alert_rate = 1.0 (1/1)

But with the current code, for each deployment:
- alert_rate = 1/2 = 0.5

This is clearly wrong. The alert rate for each deployment should be calculated based on the number of trajectories for that deployment, not the total across all deployments.

This is definitely a bug that needs to be fixed.

Let me also check if there are any other issues:

7. In commit 6d5d3cb, there's a change to the `build_request` function:
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

I don't see any issues here. It's correctly including the position in the episode for context.

8. In commit 4bb80a9, there's a test for window scoring:
```python
def test_trajectory_takes_highest_window(self):
    def reply(req):
        return "late problem\n<score>9</score>" if "window 3 of 3" in req.user else "<score>2</score>"

    backend = FakeBackend(reply)
    result = scoring.score_trajectory(one_trajectory(90), backend, CFG, "prompt")
    self.assertEqual(len(backend.requests), 3)
    self.assertEqual(result.window_scores, [2, 2, 9])
    self.assertEqual(result.raw_score, 9)
    self.assertEqual(result.rationale, "late problem")
```

This looks correct - it's verifying that the trajectory score is the highest window score.

9. In commit 806d5c7, there's a change to how batches are processed:
```python
batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
for batch in batches:
    for traj in batch:
        result = score_trajectory(traj, client, cfg, system_prompt)
        decision = decide(result.score, cfg)
        sink.record(result, decision)
        summary.scored += 1
        summary.alerts += decision in ("alert", "page")
        summary.pages += decision == "page"
    sink.commit()
```

This looks correct - it's processing trajectories in batches and committing after each batch.

After reviewing all the commits, the main bug I've identified is in the calculation of `alert_rate` in the `DeploymentStats` class. Let me propose a fix for this.

The fix would be to change:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

to:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This ensures that the alert rate for each deployment is calculated based on the number of trajectories for that specific deployment.

I'll also consider adding the alert_rate to the CSV output, as it might be useful for analysis. The current CSV output only includes scored, alerts, and errors.

Let me draft the follow-up commit:

Commit message:
```
monitor: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as (alerts for
deployment) / (total trajectories across all deployments). It should be
(alerts for deployment) / (trajectories for that deployment).

This commit fixes the calculation and adds alert_rate to the summary CSV
output for better analysis.

MON-2260
```

Now for the diff:

In `cotmon/pipeline.py`, I need to change:
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

And in `cotmon/reporting.py`, I need to update the CSV output to include alert_rate:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors,alert_rate\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Let me double-check if there are any other issues:

1. In commit ba3f0fa, the log output for per-deployment metrics uses `stats.alert_rate`:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This is correct and will now show the properly calculated alert rate.

2. The `run_metrics` table stores `alert_rate`:
```python
self.conn.executemany(
    "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
        (self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
        for name, s in sorted(per_deployment.items())
    ],
)
```

This is also correct and will now store the properly calculated alert rate.

I think this covers the main issue I found. Let me write the full diff for the follow-up commit.
