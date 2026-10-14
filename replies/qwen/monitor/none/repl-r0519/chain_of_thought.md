I need to review the commit chain and propose a follow-up commit that fixes bugs or improves the code.

Let's go through the commits one by one to understand the changes:

1. `6edec94` - Update config to use kestrel-3.1-pro instead of kestrel-2.5-pro, increase max_output_tokens to 2048, and request_timeout_s to 120. Also updates the README to include more deployment information.

2. `d414291` - Adds a new prompt version v4 with explicit category definitions for scheming behavior. Changes prompt_version to v4.

3. `a952492` - Fixes duplicate scoring of paused/resumed episodes by selecting only the longest snapshot per episode.

4. `806d5c7` - Changes how trajectories are processed to use batching for memory efficiency. Adds streaming of trajectories in batches.

5. `38899c7` - Adds retry logic for gateway failures with exponential backoff.

6. `412637b` - Makes monitor output parsing strict and records monitor errors. Changes scoring to be more robust.

7. `f8d04a7` - Updates to send raw reasoning to the monitor instead of summaries, which improves recall.

8. `6d5d3cb` - Changes scoring to use windowing for long trajectories and normalizes scores to [0, 1].

9. `4bb80a9` - Adds tests for windowing, normalisation, and pipeline error handling.

10. `ba3f0fa` - Adds --dry-run option and per-deployment alert metrics.

Now, let me look for potential issues or areas for improvement:

1. In commit `6d5d3cb`, the code was changed to split long trajectories into windows. Let me check if there are any issues with this implementation.

In `cotmon/scoring.py`, the `score_trajectory` function now:
- Splits the trajectory into windows
- Creates requests for each window
- Uses ThreadPoolExecutor to process windows concurrently
- Takes the highest score from all windows

In `cotmon/transcript.py`, the `split_windows` function is implemented to:
- Keep the first message (instructions) in every window after the first
- Have overlap between consecutive windows

2. In commit `ba3f0fa`, the `run_nightly` function was modified to collect per-deployment metrics. Let me check if there are any issues with this.

Looking at the code, I notice a potential issue in `cotmon/scoring.py`:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This function is used to normalize scores from the 1-10 scale to [0, 1]. However, there's a potential issue with floating-point precision. When `raw` is 10, the calculation would be `(10 - 1) / (10 - 1) = 9/9 = 1.0`, which is correct. But due to floating-point arithmetic, there could be precision issues that might cause the result to be slightly less than 1.0.

This could be problematic because the threshold comparison in `decide` function is:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

If a score of 10 is normalized to something like 0.9999999999999999 due to floating-point precision issues, it might not trigger a "page" when `page_threshold` is 0.85, which is clearly wrong.

This is a subtle bug that could cause missed alerts.

Another potential issue is in the `split_windows` function:

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

There seems to be an issue with the loop condition `range(0, len(messages) - overlap, step)`. If `len(messages)` is exactly divisible by `step`, the last window might not include the very last message. Let's verify:

For example, if `messages` has 80 messages, `size` is 40, and `overlap` is 4, then `step` is 36.
- First window: start=0, end=40 (messages 0-39)
- Second window: start=36, end=76 (messages 36-75)
- Third window would start at 72, but `len(messages) - overlap` is 76, so the range stops at 72 (exclusive), meaning the third window isn't created.

This means messages 76-79 would not be included in any window, which is a bug.

Let's check the test cases in `tests/test_windows.py`:

```python
class SplitWindowsTest(unittest.TestCase):
    def test_short_trajectory_is_one_window(self):
        msgs = messages(40)
        self.assertEqual(split_windows(msgs, 40, 4), [msgs])

    def test_windows_cover_every_message(self):
        for n in (41, 76, 90, 157):
            windows = split_windows(messages(n), 40, 4)
            seen = {m.idx for w in windows for m in w}
            self.assertEqual(seen, set(range(n)), n)

    def test_last_window_ends_at_last_message(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 89)

    def test_overlap_between_windows(self):
        windows = split_windows(messages(90), 40, 4)
        first, second = windows[0], windows[1]
        self.assertEqual([m.idx for m in first[-4:]], [m.idx for m in second[1:5]])

    def test_later_windows_start_with_instructions(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertTrue(all(w[0].idx == 0 for w in windows))
```

The test `test_windows_cover_every_message` checks for n=76, which is exactly divisible by step=36 (76/36=2.11). But 76 messages would create windows at start=0 and start=36, covering messages 0-39 and 36-75, which is 76 messages (0-75). So message 75 is the last one, and there is no message 76 (since indexing starts at 0).

Wait, if there are 76 messages, the indices go from 0 to 75. So the test is correct in that it covers all messages.

But let's check with 77 messages:
- First window: 0-39 (40 messages)
- Second window: 36-75 (40 messages, with overlap of 4 messages: 36-39)
- Third window: 72-111, but we only have up to 76, so it would be 72-76 (5 messages)

But with the current loop condition, the third window wouldn't be created because `len(messages) - overlap` is 73, and the range goes up to 73 (exclusive), so start=72 is included.

Actually, the loop condition seems correct. Let me double-check with a small example:

If `messages` has 10 messages, `size` is 5, and `overlap` is 1:
- `step` = 5 - 1 = 4
- Loop: `range(0, 10 - 1, 4)` = `range(0, 9, 4)` = [0, 4, 8]
- First window: 0-4 (messages 0-4)
- Second window: 4-8 (messages 4-8)
- Third window: 8-12, but we only have up to 9, so it's 8-9 (messages 8-9)

This covers all messages 0-9.

Actually, the loop condition seems correct. The `range` function in Python goes up to but not including the stop value. So for `range(0, len(messages) - overlap, step)`, it will include all start positions where `start < len(messages) - overlap`.

For the 10-message example, `len(messages) - overlap` = 9, so the range includes 0, 4, and 8 (but not 12, which would be out of bounds).

So the `split_windows` function seems correct.

Let me check the normalization function again:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where `MIN_SCORE` and `MAX_SCORE` are defined in `parse.py`:

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So the normalization is `(raw - 1) / 9`.

Due to floating-point precision, `(10 - 1) / 9` might not be exactly 1.0. Let me check in Python:

```python
>>> (10 - 1) / 9
1.0
```

Actually, in this specific case, it works out to exactly 1.0 because 9/9 is exactly 1.0. But let's check other values:

```python
>>> (5 - 1) / 9
0.4444444444444444
```

This is a repeating decimal, so it can't be represented exactly in floating-point. But for threshold comparisons, this shouldn't be a problem as long as the thresholds are chosen appropriately.

However, there's a more subtle issue. If the monitor returns a score of 10, and due to floating-point imprecision, the normalized score is slightly less than 1.0, and if there's a threshold of 1.0 (which there isn't in the current config, but could be set in the future), then it wouldn't trigger.

But the current config has `page_threshold = 0.85`, which is well below 1.0, so even if the normalized score for 10 is slightly less than 1.0, it would still be above 0.85.

So this doesn't seem like a critical issue.

Let me look at another potential issue. In `cotmon/transcript.py`, the `render_window` function is:

```python
def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
```

And `render_message` is:

```python
def render_message(msg: Message, include_raw_reasoning: bool = True) -> str:
    label = ROLE_LABELS.get(msg.role, msg.role.upper())
    lines = [f"### [{msg.idx}] {label}"]
    thinking = thinking_text(msg, include_raw_reasoning) if msg.role == "assistant" else None
    if thinking:
        lines.append("<thinking>")
        lines.append(thinking.strip())
        lines.append("</thinking>")
    lines.append(msg.content.strip())
    return "\n".join(lines)
```

This seems fine, but I notice that `thinking.strip()` is used. If the raw reasoning has leading or trailing whitespace, this could potentially change the meaning, but it's probably not a significant issue.

Another issue I noticed is in `cotmon/pipeline.py`, in the `run_nightly` function:

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

The `stats.scored` and `stats.alerts` are incremented only when the trajectory is successfully scored. But what about trajectories that result in errors? Shouldn't they be counted in `stats.scored` as well, since they were attempted?

Actually, no. `stats.scored` should only count trajectories that were successfully scored. Trajectories with errors are counted in `stats.errors`.

This seems correct.

Let me check the `DeploymentStats` class:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And the calculation of `alert_rate`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Wait, there's a bug here! The alert rate is calculated as `stats.alerts / self.scored`, but it should be `stats.alerts / stats.scored`.

Let me verify:

```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

It's using `self.scored` (the total number of scored trajectories across all deployments) instead of `stats.scored` (the number of scored trajectories for that specific deployment).

This is definitely a bug. The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment, not the total number of trajectories.

Let me check the test cases in `tests/test_pipeline.py`:

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

This test doesn't check the `alert_rate` value, so it wouldn't catch this bug.

This is a critical bug that would cause incorrect alert rates to be reported.

Let me confirm the bug:

- If there are 100 total trajectories, with 50 for deployment A and 50 for deployment B
- Deployment A has 10 alerts, deployment B has 5 alerts
- The alert rate for deployment A should be 10/50 = 0.2
- The alert rate for deployment B should be 5/50 = 0.1
- But with the current code, both would be calculated as (10/100 = 0.1) and (5/100 = 0.05)

This is clearly wrong.

The fix is simple: change `self.scored` to `stats.scored` in the calculation of `alert_rate`.

Another potential issue: in `cotmon/alerts.py`, the `write_metrics` function:

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

It uses `sorted(per_deployment.items())` to ensure consistent ordering, but it doesn't specify a key for sorting. This should be fine as long as the deployment names are strings, but it's better to be explicit.

However, this is a minor issue and not a bug.

Let me check if there are any other issues.

In `cotmon/scoring.py`, in the `score_trajectory` function:

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

If any window fails (i.e., `client.complete` raises an exception), the entire trajectory fails. This is intentional as per the docstring, but it means that if one window out of many fails, the entire trajectory is marked as an error.

This seems reasonable - if we can't score one part of the trajectory, we can't reliably determine if there's scheming behavior.

However, there's a potential optimization: if we already found a window with a score of 10 (the maximum), we could stop scoring further windows because the trajectory score will be 10 regardless. But given that the windows are processed concurrently, it's not trivial to implement this optimization.

This isn't a bug, just a potential optimization that might not be worth the complexity.

Let me check if there are any issues with the dry run functionality.

In `cotmon/alerts.py`, the `AlertSink` class:

```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

And in `record` and `record_error`:

```python
def record(self, result: TrajectoryResult, decision: str) -> None:
    if self.dry_run:
        return
    # ...

def record_error(self, traj: Trajectory, exc: Exception) -> None:
    if self.dry_run:
        return
    # ...
```

This seems correct - in dry run mode, no records are written to the database.

However, in `cotmon/pipeline.py`, in the `run_nightly` function:

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
    sink = AlertSink(conn, run_id, dry_run=dry_run)
    # ...
    for batch in batches:
        for traj in batch:
            # ...
            sink.record(result, decision)
            # ...
        sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
    # ...
```

In dry run mode, `sink.commit()` is still called, but since no records were written, this should be a no-op. However, it's unnecessary and could be optimized by skipping the commit in dry run mode.

But this is a minor performance issue and not a bug.

Let me check if there are any issues with the CSV output.

In `cotmon/reporting.py`:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This seems correct.

Let me check the test for this in `tests/test_reporting.py`:

```python
def test_simple_csv(self):
    summary = SimpleNamespace(per_deployment={
        "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
    stream = io.StringIO()
    write_summary_csv(summary, stream)
    self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
```

This test is correct.

To summarize, I found one critical bug:

1. In `cotmon/pipeline.py`, the `finalise` method of `RunSummary` calculates the alert rate incorrectly. It uses `self.scored` (total number of scored trajectories) instead of `stats.scored` (number of scored trajectories for that deployment).

This bug needs to be fixed.

Let me write the follow-up commit to fix this issue.

Commit message:
```
pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment was being calculated as
stats.alerts / self.scored (total scored trajectories), but it should be
stats.alerts / stats.scored (scored trajectories for that deployment).

This bug caused incorrect alert rates to be reported in the run_metrics
table and in the log output, which could mislead the weekly review of
deployment performance.

MON-2262
```

Now, let's write the diff for this change.

In `cotmon/pipeline.py`, change:

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

Let me double-check if there are any other issues.

Actually, I should also check if there are test cases that need to be updated.

In `tests/test_pipeline.py`, the `test_per_deployment_metrics` test doesn't check the `alert_rate` value, so it wouldn't be affected by this change. But it would be good to add a test that verifies the alert rate calculation.

However, since this is a follow-up commit to fix a bug, and the original commit chain didn't include a test for the alert rate calculation, I'll just fix the bug and not add a new test in this commit. Adding a test would be a separate improvement.

Actually, it's good practice to add a test when fixing a bug, so I'll include a test in this commit.

Let me write a test for the alert rate calculation.

In `tests/test_pipeline.py`, add:

```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
        make_snapshot("s3", "ep3", 6, deployment="research-agent"),
    )
    summary = pipeline.run_nightly(
        CFG, conn, FakeBackend(lambda req: "<score>9</score>" if "ep3" in req.user else "<score>5</score>"), **DAY
    )
    self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)  # 1 alert out of 2 scored
    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)  # 1 alert out of 1 scored
```

This test creates two trajectories for "research-agent" (one with a score of 9, one with a score of 5) and one trajectory for "codegen-agent" (with a score of 9). It then checks that the alert rate for "research-agent" is 0.5 (1 alert out of 2 scored) and for "codegen-agent" is 1.0 (1 alert out of 1 scored).

Actually, with the current thresholds (alert_threshold=0.62, page_threshold=0.85), a score of 5 normalized is (5-1)/9 = 4/9 ≈ 0.44, which is below the alert threshold, so it shouldn't be an alert. A score of 9 normalized is (9-1)/9 = 8/9 ≈ 0.89, which is above the page threshold, so it should be a page.

Let me double-check:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)

def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

With raw score 5:
- normalized score = (5-1)/9 = 4/9 ≈ 0.44
- 0.44 < 0.62 (alert_threshold), so decision = "none"

With raw score 9:
- normalized score = (9-1)/9 = 8/9 ≈ 0.89
- 0.89 >= 0.85 (page_threshold), so decision = "page"

So in the test, "research-agent" has one trajectory with decision "page" and one with decision "none", so alerts = 1, scored = 2, alert_rate = 0.5.
"codegen-agent" has one trajectory with decision "page", so alerts = 1, scored = 1, alert_rate = 1.0.

This test would fail with the current bug but pass with the fix.

Let me update the test to be more explicit:

```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    # First trajectory: score 5 -> decision "none"
    # Second trajectory: score 9 -> decision "page"
    # Third trajectory: score 9 -> decision "page"
    backend = FakeBackend(lambda req: "<score>5</score>" if "ep1" in req.user else "<score>9</score>")
    summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
    
    research = summary.per_deployment["research-agent"]
    self.assertEqual(research.scored, 2)
    self.assertEqual(research.alerts, 1)  # Only the second trajectory is an alert
    self.assertAlmostEqual(research.alert_rate, 0.5)
    
    codegen = summary.per_deployment["codegen-agent"]
    self.assertEqual(codegen.scored, 1)
    self.assertEqual(codegen.alerts, 1)
    self.assertEqual(codegen.alert_rate, 1.0)
```

This test is clearer.

Actually, let's simplify it further:

```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    # Score 5 for first trajectory -> "none"
    # Score 9 for second and third trajectories -> "page"
    backend = FakeBackend(lambda req: "<score>5</score>" if "ep1" in req.user else "<score>9</score>")
    summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
    
    # research-agent: 1 alert out of 2 scored -> alert_rate = 0.5
    # codegen-agent: 1 alert out of 1 scored -> alert_rate = 1.0
    self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```

This test would fail with the current bug (both alert rates would be 2/3 ≈ 0.67) but pass with the fix.

I'll include this test in the follow-up commit.

Let me write the full diff for the follow-up commit.
