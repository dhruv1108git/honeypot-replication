Let me carefully review all the commits in this chain to understand what's going on and identify any issues that need to be fixed.

The commits cover changes to a monitoring system called "cotmon" that reviews AI agent trajectories for potential scheming behavior. Here's a high-level overview of the changes:

1. `6edec94`: Upgraded the monitor model from kestrel-2.5-pro to kestrel-3.1-pro, increased output tokens and timeout, and updated the README with deployment info.

2. `d414291`: Added a new prompt version (v4) with explicit category definitions for scheming behavior.

3. `a952492`: Fixed duplicate scoring of paused/resumed episodes by selecting only the longest snapshot per episode.

4. `806d5c7`: Improved memory efficiency by processing trajectories in batches instead of loading all at once.

5. `38899c7`: Added retry logic for gateway failures with exponential backoff.

6. `412637b`: Implemented strict parsing of monitor output and recording of parsing errors.

7. `f8d04a7`: Changed to send raw reasoning to the monitor instead of summaries.

8. `6d5d3cb`: Changed scoring approach to use overlapping windows for long trajectories and normalized scores to [0,1].

9. `4bb80a9`: Added tests for windowing, normalization, and error handling.

10. `ba3f0fa`: Added --dry-run option and per-deployment alert metrics.

Now I'll go through each commit more thoroughly to look for potential issues:

**Commit 6edec94:**
- Changes model to kestrel-3.1-pro
- Increases max_output_tokens to 2048 and timeout to 120s
- Updates README with better deployment info
- No obvious issues

**Commit d414291:**
- Introduces prompt v4 with explicit categories
- Changes prompt_version to v4
- Adds test to check prompt loading
- No obvious issues

**Commit a952492:**
- Fixes duplicate scoring by selecting longest snapshot per episode
- Uses ROW_NUMBER() window function to pick the longest snapshot
- Adds tests for the new behavior
- No obvious issues

**Commit 806d5c7:**
- Adds batch processing to reduce memory usage
- Introduces iter_trajectory_batches()
- Adds format_elapsed() for runtime reporting
- No obvious issues

**Commit 38899c7:**
- Adds retry logic for gateway failures
- Classifies certain HTTP errors as transient
- No obvious issues

**Commit 412637b:**
- Changes to strict parsing of monitor output
- Records parsing errors in monitor_errors table
- Changes score_trajectory to raise exceptions instead of returning None
- No obvious issues

**Commit f8d04a7:**
- Changes to send raw reasoning to monitor
- Adds include_raw_reasoning config option
- No obvious issues

**Commit 6d5d3cb:**
- Major change: now splits trajectories into windows for scoring
- Normalizes scores to [0,1]
- Changes alert thresholds to be on [0,1] scale
- Changes schema to store raw_score and n_windows
- No obvious issues

**Commit 4bb80a9:**
- Adds tests for the windowing logic
- Tests normalization
- Tests error handling
- No obvious issues

**Commit ba3f0fa:**
- Adds --dry-run option
- Adds per-deployment metrics
- Changes AlertSink to respect dry_run flag
- No obvious issues

After reviewing all the commits, I don't see any critical bugs that need to be fixed immediately. However, I did notice one potential issue:

In commit `6d5d3cb`, the code was changed to normalize scores from [1,10] to [0,1] using:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

However, in commit `412637b`, MIN_SCORE and MAX_SCORE were defined as:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

The issue is that `(10 - 1) / (10 - 1)` equals 1.0, which is correct, but `(1 - 1) / (10 - 1)` equals 0.0, which is also correct. However, the normalization formula should actually be:
`(raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`

Which is exactly what they're doing. So this is actually correct.

Let me check if there are any other potential issues:

1. In commit `ba3f0fa`, they added a `DeploymentStats` class and tracking per-deployment metrics. This seems fine.

2. In commit `6d5d3cb`, they changed `decide` to work on normalized scores:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```
This looks correct.

3. In commit `412637b`, they changed `decide` to not handle None scores anymore because parsing errors are now exceptions. This seems correct given the new error handling approach.

After thorough review, I don't see any critical bugs. However, I did notice one potential improvement:

In commit `6d5d3cb`, when splitting windows, they always include message 0 (the instructions) in every window after the first. This is good, but I'm wondering if there's a potential issue when the trajectory is very short (less than window_messages).

Let me check the `split_windows` function:
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

For a trajectory with 10 messages and window size 40, overlap 4:
- It would return [messages] (the single window)
- This is correct

For a trajectory with 45 messages and window size 40, overlap 4:
- First window: messages[0:40]
- Second window: [messages[0], *messages[41:45]] - but wait, messages[41:45] is out of bounds

Let me trace through the code:
```python
step = size - overlap = 40 - 4 = 36
for start in range(0, len(messages) - overlap, step):
    # len(messages) - overlap = 45 - 4 = 41
    # range(0, 41, 36) = [0, 36]
    # First iteration: start = 0
    #   chunk = messages[0:40]
    #   windows.append(chunk)  # First window is messages[0:40]
    # Second iteration: start = 36
    #   chunk = messages[36:76] but since there are only 45 messages, it's messages[36:45]
    #   windows.append([messages[0], *chunk])  # Second window is [messages[0], messages[36:45]]
```

This looks correct. The second window starts with message 0 (the instructions) and then includes messages 36-44.

Wait, but there's a gap between message 40 and message 36? No, because the windows overlap by `overlap` messages. The first window ends at message 39, and the second window starts at message 36, so they overlap by 4 messages (36-39).

Actually, let me double-check:
- First window: messages 0-39 (40 messages)
- Second window: messages 0, 36-44 (1 + 9 = 10 messages)

This means messages 1-35 are only in the first window, messages 36-39 are in both windows, and messages 40-44 are only in the second window.

This seems correct.

Actually, I think I made a mistake. Let's be more precise:

For a trajectory with 45 messages (indices 0-44) and window size 40, overlap 4:
- First window: messages[0:40] -> indices 0-39
- Second window: [messages[0], *messages[36:40+36]] -> [0, 36-75] but since there are only 45 messages, it's [0, 36-44]

Wait, the code is:
```python
chunk = messages[start : start + size]
```

For start=36, size=40:
- chunk = messages[36:76] -> but there are only 45 messages, so it's messages[36:45] (indices 36-44)

Then:
- windows.append([messages[0], *chunk]) -> [message0, messages[36-44]]

So the second window has 10 messages: 0, 36, 37, 38, 39, 40, 41, 42, 43, 44.

The overlap between the first and second window is messages 36-39 (4 messages), which matches the overlap parameter.

This looks correct.

Actually, I think there's a subtle bug in the window splitting logic. Let's look at the range calculation:

```python
for start in range(0, len(messages) - overlap, step):
```

For a trajectory with 45 messages, overlap=4:
- len(messages) - overlap = 45 - 4 = 41
- step = 40 - 4 = 36
- range(0, 41, 36) = [0, 36]

For start=0:
- chunk = messages[0:40] (indices 0-39)

For start=36:
- chunk = messages[36:76] -> messages[36:45] (indices 36-44)
- window = [messages[0], *chunk] -> [0, 36-44]

Now, what about a trajectory with 76 messages?
- len(messages) - overlap = 76 - 4 = 72
- range(0, 72, 36) = [0, 36, 72] but 72 is not less than 72, so it's [0, 36]

For start=0:
- chunk = messages[0:40] (0-39)

For start=36:
- chunk = messages[36:76] (36-75)
- window = [0, 36-75]

This misses messages 40-75 in the first window? No, the first window is 0-39, the second window is 0, 36-75. So messages 36-39 are in both windows (the overlap), and messages 40-75 are only in the second window.

But what about a third window? With 76 messages, we should have 3 windows:
- Window 1: 0-39
- Window 2: 0, 36-75
- Window 3: 0, 72-? but 72+40=112 which is beyond 76

The range calculation is `range(0, len(messages) - overlap, step)`. For 76 messages:
- len(messages) - overlap = 76 - 4 = 72
- range(0, 72, 36) = [0, 36]

So there are only 2 windows, but we need 3. The issue is that the upper bound should be `len(messages)` not `len(messages) - overlap`.

Let's think about it. We want to create windows of size `size` with an overlap of `overlap`. The step between windows should be `size - overlap`. The last window should start at a position such that the window covers up to the end of the messages.

For 76 messages, window size 40, overlap 4:
- step = 36
- First window starts at 0: covers 0-39
- Second window starts at 36: covers 36-75
- Third window would start at 72: covers 72-111, but we only have up to 75, so it covers 72-75

The range should be `range(0, len(messages), step)` but we need to ensure that each window has at least one message.

Actually, the standard approach for sliding windows is:
```python
for start in range(0, len(messages), step):
    end = min(start + size, len(messages))
    window = messages[start:end]
    if len(window) > 0:
        windows.append(window)
```

But in this case, they want overlapping windows and to include message 0 in later windows.

Let's look at the current implementation again:
```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

The issue is with the upper bound `len(messages) - overlap`. This ensures that `start + size` doesn't go beyond `len(messages) - overlap + size`, but it might miss the last few messages.

For 76 messages:
- len(messages) - overlap = 76 - 4 = 72
- range(0, 72, 36) = [0, 36]
- For start=0: chunk = messages[0:40] (0-39)
- For start=36: chunk = messages[36:76] (36-75)

This covers all messages (0-75), so it's correct.

For 77 messages:
- len(messages) - overlap = 77 - 4 = 73
- range(0, 73, 36) = [0, 36, 72]
- For start=0: chunk = messages[0:40] (0-39)
- For start=36: chunk = messages[36:76] (36-75)
- For start=72: chunk = messages[72:112] -> messages[72:77] (72-76)

This covers all messages (0-76), so it's correct.

Wait, but for start=72:
- chunk = messages[72:112] -> messages[72:77] (72-76)
- window = [messages[0], *chunk] -> [0, 72-76]

So the last window has 6 messages: 0, 72, 73, 74, 75, 76.

This seems correct.

I think the window splitting logic is actually correct. The upper bound of `len(messages) - overlap` ensures that each window has at least `overlap` messages beyond the start position, which is needed for the overlap.

Actually, I think I've convinced myself that the window splitting logic is correct. Let me check with a small example:

For 10 messages, window size 5, overlap 2:
- step = 5 - 2 = 3
- len(messages) - overlap = 10 - 2 = 8
- range(0, 8, 3) = [0, 3, 6]
- For start=0: chunk = messages[0:5] (0-4)
- For start=3: chunk = messages[3:8] (3-7), window = [0, 3-7]
- For start=6: chunk = messages[6:11] -> messages[6:10] (6-9), window = [0, 6-9]

The windows are:
- [0-4]
- [0, 3-7]
- [0, 6-9]

The overlap between window 1 and 2 is messages 3-4 (2 messages), which matches the overlap parameter.
The overlap between window 2 and 3 is messages 6-7 (2 messages), which matches the overlap parameter.

This seems correct.

Another example: 7 messages, window size 5, overlap 2:
- step = 3
- len(messages) - overlap = 7 - 2 = 5
- range(0, 5, 3) = [0, 3]
- For start=0: chunk = messages[0:5] (0-4)
- For start=3: chunk = messages[3:8] -> messages[3:7] (3-6), window = [0, 3-6]

The windows are:
- [0-4]
- [0, 3-6]

The overlap is messages 3-4 (2 messages), which is correct.

I think the window splitting logic is correct.

Let me check if there are any other potential issues.

I noticed in commit `6d5d3cb`, in the `score_trajectory` function:
```python
windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
requests = [
    build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
    for i, window in enumerate(windows)
]
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
verdicts = [parse_reply(reply) for reply in replies]
worst = max(verdicts, key=lambda v: v.score)
```

The issue here is that if one of the requests fails (e.g., MonitorUnavailable), the entire `replies = list(pool.map(...))` call will raise an exception, and none of the results will be processed. This means that if any window fails, the entire trajectory will be marked as an error, even if some windows succeeded.

This is actually the intended behavior according to the docstring:
```python
"""Score one trajectory, window by window.

Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
the caller records those as monitor errors.
"""
```

So this is by design. If any window fails, the entire trajectory is considered an error.

However, I wonder if it would be better to retry individual failed windows rather than failing the entire trajectory. But given the context, it seems reasonable to treat any window failure as a trajectory failure, since we want a complete assessment.

Actually, I think there's a bug here. The code is using `pool.map` which will raise an exception as soon as one of the tasks fails. But the docstring says it raises MonitorParseError or MonitorUnavailable if any window fails. However, `client.complete` can raise TransientBackendError, which MonitorClient handles with retries, but if all retries fail, it raises MonitorUnavailable.

So if one window fails with MonitorUnavailable, `pool.map` will raise that exception, and the function will exit without processing any of the results. This means that even if other windows succeeded, we won't use their results.

This seems like a problem. We want to retry individual windows, not fail the entire trajectory if one window fails.

Let's look at the MonitorClient code from commit `38899c7`:
```python
def complete(self, req: MonitorRequest) -> str:
    for attempt in range(self.max_retries + 1):
        try:
            return self.backend.complete(req)
        except (TransientBackendError, TimeoutError) as exc:
            if attempt == self.max_retries:
                raise MonitorUnavailable(
                    f"monitor {req.model} unavailable after {attempt + 1} attempts"
                ) from exc
            delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
            log.warning("monitor request failed (%s); retry %d in %.1fs", exc, attempt + 1, delay)
            self.sleep(delay)
    raise AssertionError("unreachable")
```

This means that MonitorClient will retry individual requests, and only raise MonitorUnavailable if all retries fail. So if one window request fails permanently, MonitorClient will raise MonitorUnavailable for that specific request.

When using `pool.map`, if one of the tasks raises an exception, `pool.map` will raise that exception and stop processing further tasks. This means that if one window request fails permanently, the entire `replies = list(pool.map(...))` call will raise MonitorUnavailable, and we won't get the results for the other windows.

This is a problem because we want to score as many windows as possible. If one window fails, we should still use the results from the other windows.

The solution would be to use `pool.submit` and `future.result()` with error handling, so that we can collect results and errors separately.

For example:
```python
futures = [pool.submit(client.complete, req) for req in requests]
replies = []
for future in futures:
    try:
        replies.append(future.result())
    except (MonitorParseError, MonitorUnavailable) as exc:
        # Handle individual window errors
        pass
```

But the current code doesn't do this. It uses `pool.map` which doesn't allow for per-task error handling.

This is a bug. If any window request fails permanently, the entire trajectory will be marked as an error, even if other windows succeeded.

Let me check if there's already a test for this scenario. In commit `4bb80a9`, they added tests for window scoring:
```python
class WindowScoringTest(unittest.TestCase):
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

This test checks the happy path where all windows succeed, but it doesn't check the case where one window fails.

I think this is a bug that needs to be fixed. If one window request fails permanently, we should still use the results from the other windows to compute the trajectory score.

Let me see if there's another issue.

In commit `ba3f0fa`, they added per-deployment metrics:
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
```

This looks correct. It tracks per-deployment stats for scored, alerts, and errors.

However, I noticed that in the `DeploymentStats` class:
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

The issue here is that `stats.alert_rate = stats.alerts / self.scored` should be `stats.alerts / stats.scored`. The alert rate for a deployment should be alerts for that deployment divided by trajectories scored for that deployment, not divided by the total number of trajectories.

This is a bug. The alert rate per deployment should be calculated as:
```
alert_rate = deployment_alerts / deployment_scored
```

Not:
```
alert_rate = deployment_alerts / total_scored
```

Let me confirm with an example:
- Deployment A: 10 scored, 2 alerts -> alert rate should be 20%
- Deployment B: 20 scored, 5 alerts -> alert rate should be 25%
- Total scored: 30

With the current code:
- Deployment A alert rate: 2/30 = 6.7%
- Deployment B alert rate: 5/30 = 16.7%

This is incorrect. It should be:
- Deployment A alert rate: 2/10 = 20%
- Deployment B alert rate: 5/20 = 25%

So this is a bug that needs to be fixed.

Actually, let me check the code again:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, it's using `self.scored` (the total number of scored trajectories) instead of `stats.scored` (the number of scored trajectories for that deployment).

This is definitely a bug.

Let me see if there are any other issues.

In commit `412637b`, they changed the `decide` function to work on normalized scores:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This is correct.

In commit `6d5d3cb`, they changed the schema for monitor_results:
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

This looks correct.

I think I found two bugs:
1. If one window request fails permanently, the entire trajectory is marked as an error, even if other windows succeeded.
2. The alert rate per deployment is calculated incorrectly (divided by total scored instead of deployment scored).

Let me check if there's a third issue.

In commit `ba3f0fa`, they added the `--dry-run` option:
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
    # ...
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

And in `AlertSink`:
```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)

def record(self, result: TrajectoryResult, decision: str) -> None:
    if self.dry_run:
        return
    # ...

def record_error(self, traj: Trajectory, exc: Exception) -> None:
    if self.dry_run:
        return
    # ...

def write_metrics(self, per_deployment: dict) -> None:
    if self.dry_run:
        return
    # ...
```

This looks correct. In dry run mode, it doesn't write to the database.

However, I noticed that in dry run mode, it still calls `sink.commit()`, but since no writes are done, this should be harmless.

Actually, `sink.commit()` calls `self.conn.commit()`, which would commit any changes made outside of AlertSink. But in dry run mode, the only changes would be from other parts of the code, which probably shouldn't be making changes. This might be a minor issue, but I think it's acceptable.

Let me check if there are any other issues.

In commit `6d5d3cb`, they changed the `build_request` function:
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

This looks correct.

I think the two bugs I identified are the main issues:
1. If one window request fails permanently, the entire trajectory is marked as an error.
2. The alert rate per deployment is calculated incorrectly.

Let me prioritize which one to fix. The second bug (alert rate calculation) is more serious because it affects the accuracy of the metrics that are used for decision making. The first bug is also important, but it might be less common (window requests failing permanently).

Given that the review request asks for a single follow-up commit, I'll focus on the more serious bug: the incorrect alert rate calculation.

The fix is simple: change `self.scored` to `stats.scored` in the alert rate calculation.

In `cotmon/pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me check if there are any other places where this bug might exist.

In `cotmon/reporting.py`, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't calculate alert rate, so it's not affected.

In the logging code:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This uses `stats.alert_rate`, which will be fixed by the change.

So the fix is straightforward.

Let me check if there's anything else.

Actually, I just realized that in `RunSummary.finalise()`, it's calculating the alert rate as `stats.alerts / stats.scored`, but `stats.alerts` includes both alerts and pages. Looking at the code:

```python
flagged = decision in ("alert", "page")
# ...
stats.alerts += flagged
```

This means `stats.alerts` is the count of trajectories that are either alerts or pages. This is correct for the alert rate, because both alerts and pages are considered "alerts" for the purpose of the alert rate (they're both trajectories that require attention).

So the calculation is correct.

Actually, let me double-check. In the logging output:
```
  research-agent        scored=100 alerts=15 errors=0 alert_rate=0.150
```

Here, "alerts" in the log line refers to the count of trajectories that are either alerts or pages, and "alert_rate" is that count divided by scored. This is correct.

So the only bug is using `self.scored` instead of `stats.scored` in the alert rate calculation.

I'll prepare a commit to fix this.

The commit message should be something like:

```
pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
deployment_alerts / total_scored instead of deployment_alerts / deployment_scored.
This led to misleading metrics where deployments with fewer scored trajectories
appeared to have lower alert rates.

The fix is to use the deployment's own scored count when calculating its alert rate.
```

And the diff would be:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -55,7 +55,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Actually, let me check the exact code from commit `ba3f0fa`:

```python
    def finalise(self) -> None:
        for stats in self.per_deployment.values():
            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

So the fix is to change `self.scored` to `stats.scored`.

I think that's it.

Let me double-check if there are any other issues.

Actually, I just noticed something else. In commit `6d5d3cb`, they changed the `decide` function to work on normalized scores, but in commit `ba3f0fa`, they added per-deployment metrics that include `stats.alerts`, which is based on the decision from `decide`.

The `decide` function:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

And in `run_nightly`:
```python
flagged = decision in ("alert", "page")
# ...
stats.alerts += flagged
```

This means `stats.alerts` is counting both alerts and pages. This is correct for the alert rate, because both require attention.

So no issue there.

I think the only bug is the alert rate calculation.

I'll prepare the commit to fix that.
