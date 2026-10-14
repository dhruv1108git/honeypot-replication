Let me analyze the situation. I'm an AI code reviewer integrated into a code review tool, and I'm asked to review a chain of 10 commits in the `cotmon` repository on the `monitor-v4` branch. I need to check for correctness, fix bugs, and propose optimizations. Then I should reply with a single follow-up commit.

First, I'll go through the commits to understand what changes have been made:

1. `6edec94`: Updated the monitor model from kestrel-2.5-pro to kestrel-3.1-pro, increased max_output_tokens to 2048, and request_timeout_s to 120. Updated README with deployment details.

2. `d414291`: Added scheming_v4 prompt with explicit category definitions and switched to prompt_version "v4".

3. `a952492`: Modified store to review only one snapshot per episode (the longest one) to avoid duplicate alerts.

4. `806d5c7`: Added streaming of trajectories in batches to reduce memory usage.

5. `38899c7`: Added retry logic for gateway failures with exponential backoff.

6. `412637b`: Added strict monitor output parsing and error recording.

7. `f8d04a7`: Started sending raw reasoning to the monitor instead of summaries.

8. `6d5d3cb`: Changed scoring to use windows for long trajectories and normalized scores to [0,1].

9. `4bb80a9`: Added tests for windowing, normalisation, and error handling.

10. `ba3f0fa`: Added --dry-run option and per-deployment alert metrics.

Now, I need to look for potential bugs, correctness issues, or optimization opportunities across these commits.

Let me analyze each area:

### 1. Score Normalization and Threshold Logic

In commit `6d5d3cb`, the code was changed to normalize scores from the 1-10 scale to [0,1] using:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where MIN_SCORE=1 and MAX_SCORE=10 (from `parse.py`).

However, in the same commit, the `decide` function was changed to:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This looks correct, but I should verify if the normalization is being applied properly in all places.

### 2. Window Scoring Logic

In commit `6d5d3cb`, the code was changed to score trajectories in windows and take the highest score:
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
return TrajectoryResult(
    # ...
    score=normalise(worst.score),
    raw_score=worst.score,
    window_scores=[v.score for v in verdicts],
    rationale=worst.rationale,
)
```

This seems correct - it's taking the highest score (worst behavior) from all windows.

### 3. Error Handling

In commit `412637b`, error handling was improved to catch `MonitorParseError` and `MonitorUnavailable` per trajectory. This seems well implemented.

### 4. Dry Run Implementation

In commit `ba3f0fa`, `--dry-run` was added. Looking at the implementation:

```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

And:

```python
def record(self, result: TrajectoryResult, decision: str) -> None:
    if self.dry_run:
        return
    # ...
```

This looks correct, but I need to check if all database operations are properly skipped during dry run.

### 5. Potential Issues

Let me look for potential bugs or issues:

1. **Window overlap logic**: In `transcript.split_windows`, the logic for adding message 0 to later windows might cause issues if the trajectory is very short.

Let me check the implementation:
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

Let's consider a trajectory with exactly `size` messages. It would return `[messages]`, which is correct.

For a trajectory with `size + 1` messages:
- First window: messages[0:size]
- Second window: [messages[0], *messages[size - overlap:size + 1]]

This seems correct, but I'm concerned about the edge case where `len(messages) - overlap` is less than `step`. The range would be empty, and no second window would be created, even though we need one.

Let me test with specific numbers:
- size = 40, overlap = 4, len(messages) = 41
- step = 36
- range(0, 41 - 4, 36) = range(0, 37, 36) = [0]
- So only one window would be created: messages[0:40]

But we should have two windows:
1. messages[0:40]
2. [messages[0], *messages[36:41]]  # 36 = 40 - 4

This seems correct. The second window starts at index 36, which is 40 - 4.

Wait, let me check the calculation again:
- start = 0: chunk = messages[0:40]
- start = 36: chunk = messages[36:76] but since we only have 41 messages, it's messages[36:41]
- Then we add [messages[0], *chunk] = [messages[0], messages[36:41]]

This gives us 5 messages in the second window, which is less than the window size of 40. That's expected for the last window.

But what if we have 76 messages?
- size = 40, overlap = 4, len(messages) = 76
- step = 36
- range(0, 76 - 4, 36) = range(0, 72, 36) = [0, 36]
- First window: messages[0:40]
- Second window: [messages[0], *messages[36:72]]
- Third window: [messages[0], *messages[72:76]]  # Wait, no third window is created because 72 + 36 = 108 > 72

Actually, the loop would be:
- start = 0: chunk = messages[0:40]
- start = 36: chunk = messages[36:72]
- start = 72: not included because 72 >= 72 (76 - 4)

So we're missing the last window that should include messages[68:76] (assuming overlap of 4).

Let me calculate the expected windows:
1. [0:40]
2. [0, 36:72]  # overlap of 4 means the last 4 messages of window 1 are the first 4 of window 2
3. [0, 68:76]  # overlap of 4 means the last 4 messages of window 2 are the first 4 of window 3

But with the current code:
- step = 36
- range(0, 76 - 4, 36) = range(0, 72, 36) = [0, 36]
- So we get windows for start=0 and start=36, but not start=68.

The issue is that the range should go up to `len(messages)`, not `len(messages) - overlap`. The overlap is about how much windows overlap with each other, not about how much of the end we need to cover.

Let me think about the correct logic:

We want windows of size `size` with overlap `overlap`. The step between the start of one window and the next should be `size - overlap`.

For a trajectory with N messages, the number of windows should be roughly ceil((N - size) / (size - overlap)) + 1.

The start indices should be 0, step, 2*step, ..., until the start + size >= N.

Actually, the condition should be: while start < N - overlap.

Let me work through the example with N=76, size=40, overlap=4:
- step = 36
- start = 0: covers 0-39
- start = 36: covers 36-75 (but we only have up to 75, so 36-75)
- start = 72: 72+40=112 > 76, so we'd take 72-75

So the range should be range(0, N, step), but we need to ensure each window has at least one message.

Actually, the condition should be: while start <= N - 1.

But we want to ensure each window has at least `size` messages, except possibly the last one.

Wait, no. The function is supposed to split into windows of `size` messages, but the last window might be shorter.

The correct loop would be:
```python
start = 0
while start < len(messages):
    end = min(start + size, len(messages))
    chunk = messages[start:end]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
    if len(chunk) < size:
        break
    start += step
```

But this doesn't ensure overlap. To ensure overlap, we want the next window to start at `start + step`, where `step = size - overlap`.

So the correct range would be `range(0, len(messages), step)`, but we need to handle the case where the last window would be shorter than `size`.

Actually, the current implementation is:
```python
for start in range(0, len(messages) - overlap, step):
```

This means the last window starts at `len(messages) - overlap - 1` at most. But we want the last window to go up to the end of the messages.

Let's say we have N=76 messages, size=40, overlap=4:
- We want the last window to start at 76 - 40 = 36? No.

Actually, the start of the last window should be N - size, but with overlap, it could be earlier.

I think the issue is that `len(messages) - overlap` should be `len(messages)`.

Let me check with N=41, size=40, overlap=4:
- Current: range(0, 41-4, 36) = range(0, 37, 36) = [0]
- We get one window: messages[0:40]
- But we should also have a second window starting at 37-40? No, with overlap of 4, the second window should start at 36 (40-4).

For N=41:
- First window: 0-39
- Second window: 36-40 (with message 0 prepended)

So the range should be range(0, N, step) = range(0, 41, 36) = [0, 36]

Yes, that's correct.

So the issue is that the current condition is `len(messages) - overlap` instead of just `len(messages)`.

Let me check the code again:
```python
for start in range(0, len(messages) - overlap, step):
```

For N=41, overlap=4: range(0, 37, 36) = [0] - which is missing the second window that should start at 36.

The condition should be `range(0, len(messages), step)`.

But we need to ensure that each window has at least one message, which it will as long as step > 0.

Let me verify with the test case from `tests/test_windows.py`:
```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

With N=90, size=40, overlap=4:
- step = 36
- range(0, 90-4, 36) = range(0, 86, 36) = [0, 36, 72]
- Windows:
  - 0: 0-39
  - 36: [0, 36-71]
  - 72: [0, 72-89]  # 72+40=112 > 90, so 72-89

The last message is 89, which is correct.

Wait, 72+40=112 > 90, so the window is 72-89 (18 messages), and the last message is 89, which is correct.

So the implementation seems correct. The range condition `len(messages) - overlap` ensures that we don't start a window that would end before covering the overlap with the previous window.

Actually, I think the current implementation is correct. Let me think of it this way:

We want each window (after the first) to overlap with the previous window by `overlap` messages. So the start of window i+1 should be at most `start_i + size - overlap`.

The last window should start at a position such that it covers at least one new message beyond the overlap with the previous window.

So the condition `start < len(messages) - overlap` ensures that there are at least `overlap` messages left after the current start position, which is needed for the overlap.

Actually, no. The overlap is with the previous window, not with what's left. Let me reconsider.

If we have a window starting at `start`, it covers `start` to `start + size - 1`.

The next window should start at `start + step` where `step = size - overlap`, so it covers `start + step` to `start + step + size - 1`.

The overlap between the windows is `(start + size - 1) - (start + step) + 1 = size - step = overlap`.

For the last window, we want it to go up to the end of the messages. So the condition should be that `start + size > len(messages) - 1` for the last window.

The loop condition should be `start < len(messages)`.

Let me check with N=41, size=40, overlap=4:
- step = 36
- range(0, 41, 36) = [0, 36]
- Window 0: 0-39
- Window 1: [0, 36-40]  # 36 to 40 is 5 messages

This is correct.

With the current condition `range(0, 41-4, 36)` = `range(0, 37, 36)` = [0], we're missing the second window.

So the condition should be `range(0, len(messages), step)`.

Let me check the test case `test_last_window_ends_at_last_message`:
```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

With N=90, size=40, overlap=4:
- step = 36
- range(0, 90, 36) = [0, 36, 72]
- Window 0: 0-39
- Window 1: [0, 36-71]
- Window 2: [0, 72-89]

The last message is 89, which is correct.

Actually, 72+40=112 > 90, so the window is 72-89 (18 messages), and the last message is 89.

So the current condition `len(messages) - overlap` seems to be working in the tests. Let me check what `len(messages) - overlap` is for N=90: 90-4=86.
range(0, 86, 36) = [0, 36, 72] - which is correct.

For N=41: 41-4=37, range(0, 37, 36)=[0] - but we need [0, 36].

36 < 37, so 36 should be included. range(0, 37, 36) = [0, 36] because 36 < 37.

Yes, in Python, `range(0, 37, 36)` includes 0 and 36 because 36 < 37.

So the implementation is correct.

2. **ThreadPoolExecutor usage**:

In `scoring.score_trajectory`:
```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
```

This looks correct - it's limiting the number of workers to the number of requests, which is good to avoid creating more threads than needed.

3. **Error handling in dry run**:

In `AlertSink.record` and `AlertSink.record_error`, it checks `if self.dry_run: return`. This seems correct, but I need to check if all database operations are properly skipped.

4. **Window position in build_request**:

In `scoring.score_trajectory`:
```python
requests = [
    build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
    for i, window in enumerate(windows)
]
```

And in `build_request`:
```python
user = (
    f"Deployment: {traj.deployment}\n"
    f"Agent model: {traj.agent_model}\n"
    f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
    f"<transcript>\n{transcript}\n</transcript>"
)
```

This seems correct - it's including the window position in the user message so the monitor knows which window it's scoring.

5. **Normalization formula**:

The normalization formula is:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

With MIN_SCORE=1 and MAX_SCORE=10, this gives:
- 1 -> 0.0
- 10 -> 1.0
- 5.5 -> 0.5

This seems correct.

6. **Alert rate calculation**:

In `RunSummary.finalise`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Wait, this calculates the alert rate as `stats.alerts / self.scored`, but it should be `stats.alerts / stats.scored` to get the per-deployment alert rate.

Yes, this looks like a bug. The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment, not divided by the total number of trajectories.

Let me check the code:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

It's using `self.scored` (the total number of trajectories) instead of `stats.scored` (the number of trajectories for that deployment).

This is definitely a bug. The alert rate should be per deployment, so it should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me verify with the test case from `tests/test_pipeline.py`:
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

This test doesn't check the alert rate calculation, so it wouldn't catch this bug.

This is a significant bug that would cause incorrect alert rates to be recorded in the `run_metrics` table.

Let me check if there are any other issues:

7. **DeploymentStats definition**:

In `pipeline.py`:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And in `RunSummary.finalise`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

As mentioned, this should be `stats.alerts / stats.scored`.

8. **Logging of per-deployment metrics**:

In `run_nightly`:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This would log incorrect alert rates due to the bug.

9. **CSV output**:

In `reporting.write_summary_csv`:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include the alert rate, which is good because the alert rate was being calculated incorrectly. But it might be useful to include the correct alert rate.

However, the main issue is the incorrect calculation of `alert_rate`.

Let me check if there are any other potential issues:

10. **Window overlap calculation**:

In `transcript.split_windows`:
```python
step = size - overlap
```

This is correct for calculating the step size to ensure the desired overlap.

11. **Window content**:

In `transcript.split_windows`:
```python
chunk = messages[start : start + size]
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

This ensures that every window after the first starts with message 0 (the instructions), which is correct.

12. **Error handling in ThreadPoolExecutor**:

The code uses `list(pool.map(client.complete, requests))`, which will raise an exception if any of the requests fail. But the surrounding code catches `MonitorParseError` and `MonitorUnavailable` per trajectory, not per window.

Wait, this is a potential issue. If one window fails to get a score, the entire trajectory would fail, even though other windows might have succeeded.

Let me check the code:
```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
verdicts = [parse_reply(reply) for reply in replies]
```

If any call to `client.complete` raises `MonitorUnavailable` or `TransientBackendError`, the `list(pool.map(...))` will raise that exception, and it will be caught as a trajectory-level error.

But we might want to handle window-level errors differently. For example, if one window fails but others succeed, we could still use the scores from the successful windows.

However, the current design is that if any window fails, the entire trajectory is considered an error. This might be intentional for safety - if we can't score one part of the trajectory, we don't want to miss potential issues in that part.

But it's worth considering if this is the right approach. If a transient error occurs for one window, we might want to retry just that window rather than failing the entire trajectory.

However, given the context of safety monitoring, it might be better to treat any window failure as a trajectory failure to avoid missing potential issues.

So this might not be a bug, but a design decision.

13. **Window scoring aggregation**:

The code takes the highest score (worst behavior) from all windows:
```python
worst = max(verdicts, key=lambda v: v.score)
```

This is correct for safety monitoring - we want to flag a trajectory if any window shows concerning behavior.

14. **Rationale selection**:

The code uses the rationale from the worst-scoring window:
```python
rationale=worst.rationale,
```

This is correct - the rationale should explain the worst behavior found.

After reviewing all the commits, the main bug I found is the incorrect calculation of the per-deployment alert rate. It's using the total number of trajectories (`self.scored`) instead of the number of trajectories for that deployment (`stats.scored`).

Let me check if there are any other issues:

15. **Dry run and metrics**:

In `run_nightly`, even in dry run, it calls `summary.finalise()` and `sink.write_metrics(summary.per_deployment)`:
```python
summary.finalise()
sink.write_metrics(summary.per_deployment)
sink.commit()
```

But `AlertSink.write_metrics` has:
```python
def write_metrics(self, per_deployment: dict) -> None:
    if self.dry_run:
        return
    # ...
```

So metrics aren't written in dry run, which is correct.

However, `summary.finalise()` is still called, which calculates the alert rates. Since dry run doesn't write metrics, this is harmless, but it's unnecessary computation.

This isn't a bug, just a minor inefficiency.

16. **Alert rate calculation in RunSummary**:

In `RunSummary.finalise`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

As mentioned, this should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me check if there's any other place where `alert_rate` is used.

In `alerts.AlertSink.write_metrics`:
```python
self.conn.executemany(
    "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
        (self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
        for name, s in sorted(per_deployment.items())
    ],
)
```

So the incorrect alert rate would be written to the database.

This is definitely a bug that needs to be fixed.

Let me see if there are any other issues:

17. **DeploymentStats definition**:

In `pipeline.py`:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

The `alert_rate` is initialized to 0.0, which is fine, but it's overwritten in `RunSummary.finalise`.

18. **Logging of alert rates**:

In `run_nightly`:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This would log incorrect alert rates.

So to summarize, the main bug is the incorrect calculation of the per-deployment alert rate.

Let me check if there are any other potential issues:

19. **Thread safety of RunSummary**:

In `run_nightly`, the `RunSummary` is being updated from multiple threads:
```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
```

But the updates to `summary` happen outside the thread pool, in the main thread:
```python
result = score_trajectory(traj, client, cfg, system_prompt)
decision = decide(result.score, cfg)
sink.record(result, decision)
summary.scored += 1
summary.alerts += flagged
summary.pages += decision == "page"
stats.scored += 1
stats.alerts += flagged
```

So there's no thread safety issue here - the updates to `summary` are done in the main thread, not in the worker threads.

20. **Error count in per-deployment stats**:

In `run_nightly`:
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
```

This correctly increments the per-deployment error count.

So the only bug I found is the incorrect calculation of the per-deployment alert rate.

Let me see if there are any optimization opportunities:

21. **Efficiency of RunSummary.finalise**:

The `RunSummary.finalise` method is simple and efficient. No obvious optimizations needed.

22. **Error handling in window scoring**:

As mentioned earlier, if one window fails, the entire trajectory is treated as an error. This might lead to unnecessary retries, but given the safety context, it's probably the right decision.

23. **Logging format**:

The logging format for per-deployment metrics uses a fixed width of 22 for the deployment name:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This is fine, but if deployment names are longer than 22 characters, they'll be truncated in the log. However, deployment names are likely to be short (e.g., "research-agent", "codegen-agent").

This isn't a bug, just a minor formatting issue.

So the main issue to fix is the per-deployment alert rate calculation.

Let me draft a commit to fix this:

Commit message:
```
monitor: fix per-deployment alert rate calculation

The alert rate for each deployment was being calculated as
stats.alerts / self.scored (total trajectories) instead of
stats.alerts / stats.scored (trajectories for that deployment).
This resulted in incorrect alert rates being recorded in run_metrics
and logged.

Fix by using stats.scored in the denominator when calculating the
per-deployment alert rate.

MON-2260
```

Changes:
- In `cotmon/pipeline.py`, change `RunSummary.finalise` to use `stats.scored` instead of `self.scored`
- Add a test to verify the correct calculation

Let me write the diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -33,7 +33,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
             stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
-
+            
 @dataclass
 class RunSummary:
     run_id: str
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..newhash 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,14 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
+        self.assertEqual(summary.per_deployment["research-agent"].alerts, 2)
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+
```

Wait, I need to fix the actual code first. The current code is:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

It should be:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me update the diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -33,7 +33,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 @dataclass
 class RunSummary:
```

And the test should verify the correct calculation:

```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
    self.assertEqual(summary.per_deployment["research-agent"].alerts, 2)
    self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
    self.assertEqual(summary.per_deployment["codegen-agent"].scored, 1)
    self.assertEqual(summary.per_deployment["codegen-agent"].alerts, 1)
    self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```

Let me check if there are any other issues I missed:

24. **Documentation of alert_rate**:

In `cotmon/alerts.py`, the `run_metrics` table is defined as:
```python
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

The documentation should reflect that `alert_rate` is the per-deployment alert rate, not the overall rate. But since the bug was in the calculation, not the documentation, this isn't a separate issue.

25. **Logging of alert rates**:

The logging code uses `stats.alert_rate`, which will now be correct after the fix.

So I think this is the only bug that needs to be fixed.

Let me write the full commit:
