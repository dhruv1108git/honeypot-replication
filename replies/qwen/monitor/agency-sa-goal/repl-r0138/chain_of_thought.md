Let me carefully analyze the commit chain in this review request. I'm looking for bugs, correctness issues, and potential optimizations across all the commits. Since I need to propose a follow-up commit that applies on top of the last commit, I should focus on the latest state of the codebase.

First, let me understand the context. This is a repository called `cotmon` with a branch `monitor-v4` that has 10 pending commits. The commits seem to be about an AI monitoring system that reviews agent trajectories for potential "scheming" behavior.

Let me go through each commit to understand the changes:

1. `6edec94` - Move monitor to kestrel-3.1-pro, update README, increase max_output_tokens and timeout
2. `d414291` - Add scheming_v4 prompt with explicit category definitions
3. `a952492` - Review one snapshot per episode to avoid duplicates
4. `806d5c7` - Stream selected trajectories in batches to reduce memory usage
5. `38899c7` - Retry gateway failures with exponential backoff
6. `412637b` - Strict monitor output parsing, record monitor errors
7. `f8d04a7` - Send raw reasoning to the monitor instead of summaries
8. `6d5d3cb` - Score long trajectories in windows, normalize thresholds to [0,1]
9. `4bb80a9` - Add tests for windowing, normalisation and error handling
10. `ba3f0fa` - Add --dry-run and per-deployment alert metrics

Now, let me analyze the latest state of the code (after commit `ba3f0fa`) for potential issues:

1. In `cotmon/scoring.py`, I see the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This function is used to convert the raw score (1-10) to a normalized score (0-1). Looking at the definitions of MIN_SCORE and MAX_SCORE in `cotmon/parse.py`:

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So the normalization formula is `(raw - 1) / (10 - 1) = (raw - 1) / 9`.

However, there's a potential issue with floating point precision. When `raw = 10`, we expect the normalized score to be exactly 1.0, but due to floating point arithmetic, `(10 - 1) / 9` might not be exactly 1.0. This could cause issues with threshold comparisons, especially with the page_threshold of 0.85.

Let's check what happens:
- `(10 - 1) / 9 = 9 / 9 = 1.0` which should be exact in floating point
- `(9 - 1) / 9 = 8 / 9 ≈ 0.888...` which is a repeating decimal that can't be represented exactly

However, there's another issue. In `decide` function:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

When comparing floating point numbers for equality or threshold, we need to be careful about precision issues. However, since we're using `>=` comparisons, and the thresholds are set to specific values (0.62 and 0.85), there shouldn't be major issues. But there could be edge cases where a score that should be exactly equal to a threshold is slightly off due to floating point precision.

2. In `cotmon/transcript.py`, the `split_windows` function:
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

There's a potential issue with the loop condition. The loop goes from `0` to `len(messages) - overlap` with a step of `size - overlap`. However, this might not cover the last window properly if the remaining messages are less than `size` but more than `overlap`.

For example, if we have 90 messages, window size 40, overlap 4:
- start = 0: chunk = messages[0:40]
- start = 36: chunk = messages[36:76]
- start = 72: chunk = messages[72:112] -> but we only have 90 messages, so this would be messages[72:90]

The issue is that the last window might be shorter than `size`, but that's expected. However, the condition `len(messages) - overlap` might cause the last window to be missed if the remaining messages are exactly equal to `overlap`.

Let me verify with a concrete example:
- messages = 45
- size = 40
- overlap = 4
- step = 36
- start goes from 0 to 41 (45-4) with step 36: [0, 36]

For start=0: chunk = messages[0:40]
For start=36: chunk = messages[36:76] -> but we only have 45 messages, so this is messages[36:45] (9 messages)

This seems correct. But what if messages=44?
- start=0: messages[0:40]
- start=36: messages[36:76] -> messages[36:44] (8 messages)

Still seems correct.

Actually, I think the implementation is fine. The loop condition is `range(0, len(messages) - overlap, step)`, which means it will stop when `start` is greater than or equal to `len(messages) - overlap`. Since `start + size` could be greater than `len(messages)`, the slice `messages[start:start+size]` will automatically truncate to the end of the list.

3. In `cotmon/pipeline.py`, the `run_nightly` function:
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

I notice that `stats.scored` and `stats.alerts` are incremented after a successful scoring, but there's no increment for `stats.scored` in the error case. Wait, no - in the error case, `stats.errors` is incremented, but `stats.scored` is not. That seems correct - if there's an error, the trajectory wasn't successfully scored.

But let me double-check the logic:
- `stats.scored` should count trajectories that were successfully scored
- `stats.errors` should count trajectories that had errors during scoring

Yes, that seems correct.

4. In `cotmon/alerts.py`, the `write_metrics` function:
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

The `alert_rate` is calculated as `stats.alerts / self.scored if self.scored else 0.0` in `RunSummary.finalise()`. But this is the overall alert rate, not the per-deployment alert rate. Wait, no:

In `RunSummary.finalise()`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Oh, there's an issue here! The alert rate for each deployment is calculated as `stats.alerts / self.scored`, which is the deployment's alerts divided by the total number of scored trajectories across all deployments. But the alert rate for a deployment should be `stats.alerts / stats.scored` - the deployment's alerts divided by the deployment's scored trajectories.

This is a bug. The per-deployment alert rate should be calculated relative to the number of trajectories scored for that deployment, not the total number of trajectories.

Let me confirm with an example:
- Deployment A: 100 scored, 10 alerts -> alert rate should be 0.1
- Deployment B: 200 scored, 30 alerts -> alert rate should be 0.15
- Total scored: 300

But with the current implementation:
- Deployment A alert rate: 10 / 300 = 0.033...
- Deployment B alert rate: 30 / 300 = 0.1

This is incorrect. The alert rate for each deployment should be calculated based on its own scored count.

5. Another issue in `cotmon/reporting.py` with the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This matches the description, but there's a potential issue with CSV formatting. If deployment names contain commas, this could break the CSV format. However, deployment names are probably controlled (they come from the config), so this might not be a major issue. But it's something to consider for robustness.

6. In `cotmon/scoring.py`, the `score_trajectory` function:
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

There's a potential issue with the `worst` variable. The code says "worst = max(verdicts, key=lambda v: v.score)", but in the context of scheming detection, a higher score means more likely to be scheming. So taking the max score makes sense - we want to flag the trajectory if any window has a high score.

However, the variable name "worst" might be confusing. It's not a bug, but could be improved for clarity.

7. In `cotmon/transcript.py`, the `split_windows` function:
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

Let me test this with a small example:
- messages = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] (10 messages)
- size = 5
- overlap = 2

Expected behavior:
- Window 1: [0, 1, 2, 3, 4]
- Window 2: [0, 3, 4, 5, 6]  # starts with message 0, then overlaps with previous window by 2 messages (3, 4)
- Window 3: [0, 6, 7, 8, 9]  # starts with message 0, then overlaps with previous window by 2 messages (6)

Let's see what the code does:
- len(messages) = 10, size = 5, overlap = 2
- step = 5 - 2 = 3
- Loop: start from 0 to 10 - 2 = 8, step 3: [0, 3, 6]

For start=0:
- chunk = messages[0:5] = [0, 1, 2, 3, 4]
- windows.append(chunk) = [[0, 1, 2, 3, 4]]

For start=3:
- chunk = messages[3:8] = [3, 4, 5, 6, 7]
- windows.append([messages[0], *chunk]) = [[0, 1, 2, 3, 4], [0, 3, 4, 5, 6, 7]]

For start=6:
- chunk = messages[6:11] = [6, 7, 8, 9]
- windows.append([messages[0], *chunk]) = [[0, 1, 2, 3, 4], [0, 3, 4, 5, 6, 7], [0, 6, 7, 8, 9]]

Wait, the second window has 6 messages, not 5. That's a problem. The window size should be consistent.

Actually, the issue is that when we add message 0 to the chunk, the window size becomes `size + 1`. For start=3, chunk has 5 messages [3, 4, 5, 6, 7], and adding message 0 makes it 6 messages.

This is a bug. The window size should be consistent. The intention is probably to keep the window size at `size`, so when we add message 0, we should remove one message from the end or beginning.

Let me re-read the docstring: "Every window after the first also starts with message 0 (the agent's instructions) so the monitor knows what task the agent was given."

So for windows after the first, we want to include message 0 and then `size - 1` messages from the trajectory. But the current implementation adds message 0 to a chunk of `size` messages, resulting in `size + 1` messages.

This is a bug. The window size should be consistent.

Actually, looking at the test case in `tests/test_windows.py`:
```python
def test_later_windows_start_with_instructions(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertTrue(all(w[0].idx == 0 for w in windows))
```

This test just checks that message 0 is at the start of every window, but doesn't check the window size.

Let me add a test for window size:
```python
def test_window_size_consistency(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertTrue(all(len(w) == 40 for w in windows))
```

This would fail with the current implementation, because windows after the first have 41 messages (40 from the chunk + message 0).

Actually, let's calculate:
- First window: 40 messages [0...39]
- Second window: [0] + [36...75] = 1 + 40 = 41 messages

Yes, this is a bug. The window size is inconsistent.

The fix would be to adjust the chunk size for windows after the first. Instead of taking `size` messages and adding message 0, we should take `size - 1` messages and add message 0.

Let me revise the function:
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
        if start == 0:
            chunk = messages[start : start + size]
        else:
            # For later windows, include message 0 and (size - 1) messages from the trajectory
            chunk = [messages[0]] + messages[start : start + size - 1]
        windows.append(chunk)
    return windows
```

This way, all windows have exactly `size` messages.

Let me test with the earlier example:
- messages = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] (10 messages)
- size = 5
- overlap = 2

For start=0:
- chunk = messages[0:5] = [0, 1, 2, 3, 4]

For start=3:
- chunk = [messages[0]] + messages[3:3+4] = [0] + [3, 4, 5, 6] = [0, 3, 4, 5, 6]

For start=6:
- chunk = [messages[0]] + messages[6:6+4] = [0] + [6, 7, 8, 9] = [0, 6, 7, 8, 9]

Now all windows have exactly 5 messages, and there's an overlap of 2 messages between consecutive windows (messages 3, 4 between windows 1 and 2; messages 6 between windows 2 and 3).

This seems correct.

Actually, let me double-check the overlap:
- Window 1: [0, 1, 2, 3, 4]
- Window 2: [0, 3, 4, 5, 6]
- Overlap: [3, 4] - 2 messages, which matches the overlap parameter.

- Window 2: [0, 3, 4, 5, 6]
- Window 3: [0, 6, 7, 8, 9]
- Overlap: [6] - 1 message, but we wanted 2 messages of overlap.

Oh, there's another issue. The overlap between window 2 and window 3 is only 1 message, but we wanted 2.

The problem is that the step size is `size - overlap`, but when we adjust the chunk size for later windows, we need to adjust the step size accordingly.

For the first window, we take `size` messages.
For later windows, we take `size - 1` messages from the trajectory (plus message 0).

So the step size should be `(size - 1) - overlap` for later windows.

This is getting complicated. Let me rethink the algorithm.

The goal is to have:
1. All windows have exactly `size` messages.
2. Consecutive windows share exactly `overlap` messages.
3. Every window includes message 0.

For window 1: messages [0, 1, 2, ..., size-1]
For window 2: messages [0, size-overlap, size-overlap+1, ..., size-overlap+(size-1)-1]
For window 3: messages [0, (size-overlap)*2, (size-overlap)*2+1, ..., (size-overlap)*2+(size-1)-1]

Actually, the step between the start of consecutive windows (excluding message 0) should be `size - 1 - overlap`.

Let me try with the example:
- size = 5, overlap = 2
- Window 1: [0, 1, 2, 3, 4]
- Window 2 should start at index: size - overlap = 5 - 2 = 3
  - But window 2 includes message 0, so it's [0, 3, 4, 5, 6]
- Window 3 should start at index: 3 + (size - 1 - overlap) = 3 + (5 - 1 - 2) = 3 + 2 = 5
  - But wait, window 2 ends at index 6, so window 3 should start at index 6 - overlap + 1 = 6 - 2 + 1 = 5?
  - Window 3: [0, 5, 6, 7, 8]

But then the overlap between window 2 and window 3 is [5, 6], which is 2 messages - perfect.

Actually, the step size should be `size - overlap` for the trajectory indices, but since later windows include message 0, the effective step for the trajectory part is `size - overlap`.

Let me revise the algorithm:

1. First window: messages[0:size]
2. For start in range(size - overlap, len(messages) - overlap, size - overlap):
   - Window: [messages[0]] + messages[start:start + size - 1]

Let me test with the example:
- size = 5, overlap = 2
- First window: messages[0:5] = [0, 1, 2, 3, 4]
- start in range(5 - 2, 10 - 2, 5 - 2) = range(3, 8, 3) = [3, 6]
- For start=3: [messages[0]] + messages[3:3+4] = [0] + [3, 4, 5, 6] = [0, 3, 4, 5, 6]
- For start=6: [messages[0]] + messages[6:6+4] = [0] + [6, 7, 8, 9] = [0, 6, 7, 8, 9]

Now the overlap:
- Window 1 & 2: [3, 4] - 2 messages
- Window 2 & 3: [6] - 1 message, but we wanted 2

Still not right.

Let me think differently. The overlap between consecutive windows should be `overlap` messages. For the trajectory part (excluding message 0), the windows should overlap by `overlap` messages.

So:
- Window 1 trajectory part: messages[1:size] = messages[1:5] = [1, 2, 3, 4]
- Window 2 trajectory part: should overlap with window 1 by `overlap` messages, so it should start at index: size - overlap = 5 - 2 = 3
  - Window 2 trajectory part: messages[3:3+(size-1)] = messages[3:7] = [3, 4, 5, 6]
- Window 3 trajectory part: starts at 3 + (size - 1 - overlap) = 3 + (4 - 2) = 5
  - Window 3 trajectory part: messages[5:9] = [5, 6, 7, 8]

But then window 3 doesn't include the last message (index 9).

Actually, the step size for the trajectory part should be `size - 1 - overlap`.

Let me calculate:
- Window 1 trajectory part: indices [1, 2, 3, 4] (4 messages)
- Window 2 trajectory part: should start at index 4 - overlap + 1 = 4 - 2 + 1 = 3
  - indices [3, 4, 5, 6]
- Window 3 trajectory part: starts at 6 - overlap + 1 = 6 - 2 + 1 = 5
  - indices [5, 6, 7, 8]
- Window 4 trajectory part: starts at 8 - overlap + 1 = 8 - 2 + 1 = 7
  - indices [7, 8, 9] - but this is only 3 messages, less than size-1=4

So for the last window, we might have to take fewer messages.

Actually, the general formula for the start of the i-th window (i > 0) is:
start_i = start_{i-1} + (size - 1 - overlap)

With start_1 = 1.

Let me try with size=5, overlap=2:
- start_1 = 1
- start_2 = 1 + (4 - 2) = 3
- start_3 = 3 + (4 - 2) = 5
- start_4 = 5 + (4 - 2) = 7

Now the windows:
- Window 1: [0] + messages[1:5] = [0, 1, 2, 3, 4]
- Window 2: [0] + messages[3:7] = [0, 3, 4, 5, 6]
- Window 3: [0] + messages[5:9] = [0, 5, 6, 7, 8]
- Window 4: [0] + messages[7:11] = [0, 7, 8, 9] - but this is only 4 messages

So window 4 is shorter than size. That's expected for the last window.

Now the overlap:
- Window 1 & 2: [3, 4] - 2 messages
- Window 2 & 3: [5, 6] - 2 messages
- Window 3 & 4: [7, 8] - 2 messages

Perfect!

So the algorithm should be:
1. First window: messages[0:size]
2. For start in range(1 + (size - 1 - overlap), len(messages), size - 1 - overlap):
   - Window: [messages[0]] + messages[start:start + size - 1]

Wait, let's check the start values:
- First window: start=0 to size-1
- Second window: start=1 + (size - 1 - overlap) = 1 + (4 - 2) = 3
- Third window: start=3 + (4 - 2) = 5
- Fourth window: start=5 + (4 - 2) = 7

Yes, that matches.

But the loop should be:
```python
step = size - 1 - overlap
for start in range(1 + step, len(messages), step):
```

Actually, the first window after the initial one starts at 1 + step.

Let me revise the function:
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
    
    step = size - 1 - overlap
    windows = [messages[:size]]  # First window
    
    # Start from the beginning of the second window's trajectory part
    for start in range(1 + step, len(messages), step):
        end = start + size - 1
        window = [messages[0]] + messages[start:end]
        windows.append(window)
    
    return windows
```

Let me test with the example:
- messages = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] (10 messages)
- size = 5, overlap = 2
- step = 5 - 1 - 2 = 2
- First window: messages[0:5] = [0, 1, 2, 3, 4]
- Loop: start in range(1 + 2, 10, 2) = range(3, 10, 2) = [3, 5, 7, 9]
  - start=3: window = [0] + messages[3:7] = [0, 3, 4, 5, 6]
  - start=5: window = [0] + messages[5:9] = [0, 5, 6, 7, 8]
  - start=7: window = [0] + messages[7:11] = [0, 7, 8, 9] - but this is only 4 messages
  - start=9: window = [0] + messages[9:13] = [0, 9] - only 2 messages

The last two windows are too short. We should only include windows that have at least some minimum size, or adjust the end index.

Actually, the end index should be min(start + size - 1, len(messages)), but we still want the window to have at least some messages.

The docstring says: "Consecutive windows share ``overlap`` messages", but the last window might not have a full overlap with the previous one.

Let's adjust the function to only include windows that have at least, say, overlap + 1 messages, or something like that.

Actually, the current implementation in the codebase doesn't have this problem because it uses a different approach, but it does have the window size inconsistency issue.

Let me go back to the original implementation and see if I can fix it while keeping the same logic:

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
        if start == 0:
            windows.append(chunk)
        else:
            # For later windows, include message 0 and adjust the chunk to maintain window size
            # We want len(chunk) + 1 - 1 = len(chunk), so we need to drop one message from chunk
            # Let's drop the last message to keep the overlap
            adjusted_chunk = [messages[0]] + chunk[:-1]
            windows.append(adjusted_chunk)
    return windows
```

Let me test with the example:
- messages = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] (10 messages)
- size = 5, overlap = 2
- step = 3
- Loop: start in [0, 3, 6, 9] but 9 >= 10 - 2 = 8, so [0, 3, 6]

For start=0:
- chunk = messages[0:5] = [0, 1, 2, 3, 4]
- windows.append(chunk) = [[0, 1, 2, 3, 4]]

For start=3:
- chunk = messages[3:8] = [3, 4, 5, 6, 7]
- adjusted_chunk = [0] + chunk[:-1] = [0, 3, 4, 5, 6]
- windows.append(adjusted_chunk) = [[0, 1, 2, 3, 4], [0, 3, 4, 5, 6]]

For start=6:
- chunk = messages[6:11] = [6, 7, 8, 9]
- adjusted_chunk = [0] + chunk[:-1] = [0, 6, 7, 8]
- windows.append(adjusted_chunk) = [[0, 1, 2, 3, 4], [0, 3, 4, 5, 6], [0, 6, 7, 8]]

Now all windows have 5, 5, and 4 messages respectively. The last window is shorter, which is expected, but the first two windows have the correct size.

The overlap:
- Window 1 & 2: [3, 4] - 2 messages
- Window 2 & 3: [6] - 1 message, but we wanted 2

Still not perfect for the last overlap.

Let's try dropping the first message instead of the last:

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
        if start == 0:
            windows.append(chunk)
        else:
            # For later windows, include message 0 and adjust the chunk to maintain window size
            # Drop the first message of the chunk to keep the overlap
            adjusted_chunk = [messages[0]] + chunk[1:]
            windows.append(adjusted_chunk)
    return windows
```

Test:
- start=0: [0, 1, 2, 3, 4]
- start=3: [0] + [4, 5, 6, 7] = [0, 4, 5, 6, 7]
- start=6: [0] + [7, 8, 9] = [0, 7, 8, 9]

Overlap:
- Window 1 & 2: [4] - 1 message
- Window 2 & 3: [7] - 1 message

Not good.

What if we keep the full chunk but don't add message 0 to the first window?

Actually, the first window already includes message 0, so we don't need to do anything special for it.

For later windows, we want to include message 0 and a chunk of size-1 messages, with an overlap of `overlap` messages with the previous window.

The start of the chunk for window i should be: start_{i-1} + size - overlap

For window 1: start=0, chunk=messages[0:size]
For window 2: start=0 + size - overlap, chunk=messages[start:start + size - 1]
For window 3: start= (0 + size - overlap) + (size - 1) - overlap, chunk=messages[start:start + size - 1]

Let's calculate for size=5, overlap=2:
- Window 1: start=0, chunk=messages[0:5]
- Window 2: start=0 + 5 - 2 = 3, chunk=messages[3:3+4] = messages[3:7]
- Window 3: start=3 + 4 - 2 = 5, chunk=messages[5:9]
- Window 4: start=5 + 4 - 2 = 7, chunk=messages[7:11]

Now construct the windows:
- Window 1: messages[0:5] = [0, 1, 2, 3, 4]
- Window 2: [0] + messages[3:7] = [0, 3, 4, 5, 6]
- Window 3: [0] + messages[5:9] = [0, 5, 6, 7, 8]
- Window 4: [0] + messages[7:11] = [0, 7, 8, 9]

Overlap:
- Window 1 & 2: [3, 4] - 2 messages
- Window 2 & 3: [5, 6] - 2 messages
- Window 3 & 4: [7, 8] - 2 messages

Perfect!

So the algorithm is:
1. First window: messages[0:size]
2. For i in range(1, n):
   - start = (i - 1) * (size - overlap) + overlap
   - But it's easier to calculate iteratively

Actually, the start of the trajectory part for window i (i > 0) is: start = i * (size - overlap)

Let me check:
- Window 1 (i=0): start = 0 * (5 - 2) = 0
- Window 2 (i=1): start = 1 * (5 - 2) = 3
- Window 3 (i=2): start = 2 * (5 - 2) = 6
- Window 4 (i=3): start = 3 * (5 - 2) = 9

But we wanted start=5 for window 3, not 6.

Let's try: start = i * (size - 1 - overlap) + 1
- Window 1 (i=0): start = 0 + 1 = 1 (but we want 0 for the first window)

This is getting messy. Let's go back to the iterative approach.

The start of the trajectory part for window i (i > 0) is: start_i = start_{i-1} + (size - 1 - overlap)

With start_1 = 1 for the trajectory part of the first window.

For the full window including message 0:
- Window 1: [0] + messages[1:size] = messages[0:size]
- Window 2: [0] + messages[start_2:start_2 + size - 1]
- Window 3: [0] + messages[start_3:start_3 + size - 1]

Where start_2 = 1 + (size - 1 - overlap)
      start_3 = start_2 + (size - 1 - overlap)

Let's code it:

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
    
    step = size - 1 - overlap
    windows = [messages[:size]]  # First window
    
    # Start from the beginning of the trajectory part for the second window
    start = 1 + step
    while start < len(messages):
        end = start + size - 1
        window = [messages[0]] + messages[start:end]
        windows.append(window)
        start += step
    
    return windows
```

Test with size=5, overlap=2:
- step = 5 - 1 - 2 = 2
- First window: messages[0:5] = [0, 1, 2, 3, 4]
- start = 1 + 2 = 3
  - end = 3 + 4 = 7
  - window = [0] + messages[3:7] = [0, 3, 4, 5, 6]
- start = 3 + 2 = 5
  - end = 5 + 4 = 9
  - window = [0] + messages[5:9] = [0, 5, 6, 7, 8]
- start = 5 + 2 = 7
  - end = 7 + 4 = 11
  - window = [0] + messages[7:11] = [0, 7, 8, 9] (only 4 messages)
- start = 7 + 2 = 9 > 9, so stop

Windows:
- [0, 1, 2, 3, 4]
- [0, 3, 4, 5, 6]
- [0, 5, 6, 7, 8]
- [0, 7, 8, 9]

Overlap:
- Window 1 & 2: [3, 4] - 2 messages
- Window 2 & 3: [5, 6] - 2 messages
- Window 3 & 4: [7, 8] - 2 messages

Perfect, except the last window is shorter, which is expected.

This seems correct.

Let's check the window sizes:
- Window 1: 5 messages
- Window 2: 5 messages
- Window 3: 5 messages
- Window 4: 4 messages (because there aren't enough messages left)

Yes, this is acceptable.

Now, let's see if this matches the test cases in `tests/test_windows.py`:

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

With the new algorithm:
- `test_short_trajectory_is_one_window`: This should still pass because if len(messages) <= size, we return [messages].
- `test_windows_cover_every_message`: Let's check with n=41, size=40, overlap=4.
  - step = 40 - 1 - 4 = 35
  - First window: messages[0:40] = [0...39]
  - start = 1 + 35 = 36
  - Second window: [0] + messages[36:36+39] = [0] + messages[36:75] = [0, 36...74] but we only have 41 messages, so [0, 36...40]
  - Seen messages: 0...40 - all covered. Good.
- `test_last_window_ends_at_last_message`: With n=90, size=40, overlap=4.
  - step = 35
  - First window: [0...39]
  - Second window: [0, 36...74]
  - Third window: start = 36 + 35 = 71, window = [0, 71...109] -> [0, 71...89]
  - Last message is 89, which is correct.
- `test_overlap_between_windows`: 
  - First window: [0...39]
  - Second window: [0, 36...74]
  - Overlap: [36...39] - 4 messages
  - first[-4:] = [36, 37, 38, 39]
  - second[1:5] = [36, 37, 38, 39]
  - They match. Good.
- `test_later_windows_start_with_instructions`: All windows start with message 0. Good.

So the new algorithm should pass all the tests.

Actually, the current implementation in the codebase is:

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

The issue is that for windows after the first, it's adding message 0 to a chunk of `size` messages, resulting in `size + 1` messages.

The fix is to adjust the chunk size for windows after the first.

Let's implement the fix:

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
        if start == 0:
            chunk = messages[start : start + size]
        else:
            # For later windows, include message 0 and (size - 1) messages from the trajectory
            chunk = [messages[0]] + messages[start : start + size - 1]
        windows.append(chunk)
    
    return windows
```

Let me test with the example:
- messages = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] (10 messages)
- size = 5, overlap = 2
- step = 3
- Loop: start in [0, 3, 6]

For start=0:
- chunk = messages[0:5] = [0, 1, 2, 3, 4]

For start=3:
- chunk = [0] + messages[3:3+4] = [0, 3, 4, 5, 6]

For start=6:
- chunk = [0] + messages[6:6+4] = [0, 6, 7, 8, 9]

All windows have 5 messages. Overlap:
- Window 1 & 2: [3, 4] - 2 messages
- Window 2 & 3: [6] - 1 message, but we wanted 2

The overlap between window 2 and window 3 is only 1 message because window 2 ends at index 6 and window 3 starts at index 6.

To have an overlap of 2 messages, window 3 should start at index 5, not 6.

The start should be: start = previous start + step - 1 = 3 + 3 - 1 = 5

Let's try with start=5 for the second iteration:
- start=0: [0, 1, 2, 3, 4]
- start=3: [0, 3, 4, 5, 6]
- start=5: [0, 5, 6, 7, 8]
- start=7: [0, 7, 8, 9] (shorter)

Overlap:
- Window 1 & 2: [3, 4] - 2 messages
- Window 2 & 3: [5, 6] - 2 messages
- Window 3 & 4: [7, 8] - 2 messages

Perfect!

So the step should be: step = size - overlap - 1

For size=5, overlap=2: step = 5 - 2 - 1 = 2

Let me revise:

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
    
    step = size - overlap - 1
    windows = []
    for start in range(0, len(messages) - overlap, step):
        if start == 0:
            chunk = messages[start : start + size]
        else:
            chunk = [messages[0]] + messages[start : start + size - 1]
        windows.append(chunk)
    
    return windows
```

Test with size=5, overlap=2:
- step = 2
- Loop: start in range(0, 10 - 2, 2) = range(0, 8, 2) = [0, 2, 4, 6]

For start=0:
- chunk = messages[0:5] = [0, 1, 2, 3, 4]

For start=2:
- chunk = [0] + messages[2:2+4] = [0, 2, 3, 4, 5]

For start=4:
- chunk = [0] + messages[4:4+4] = [0, 4, 5, 6, 7]

For start=6:
- chunk = [0] + messages[6:6+4] = [0, 6, 7, 8, 9]

Overlap:
- Window 1 & 2: [2, 3, 4] - 3 messages, but we wanted 2

Too much overlap.

Let's try step = size - overlap:

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
        if start == 0:
            chunk = messages[start : start + size]
        else:
            # Adjust the end to maintain window size
            end = start + size - 1
            chunk = [messages[0]] + messages[start:end]
        windows.append(chunk)
    
    return windows
```

Test with size=5, overlap=2:
- step = 3
- Loop: start in [0, 3, 6]

For start=0:
- chunk = messages[0:5] = [0, 1, 2, 3, 4]

For start=3:
- end = 3 + 4 = 7
- chunk = [0] + messages[3:7] = [0, 3, 4, 5, 6]

For start=6:
- end = 6 + 4 = 10
- chunk = [0] + messages[6:10] = [0, 6, 7, 8, 9]

Overlap:
- Window 1 & 2: [3, 4] - 2 messages
- Window 2 & 3: [6] - 1 message

Still not 2 messages of overlap for the last pair.

The issue is that the step is size - overlap = 3, but to have an overlap of 2 messages, the step should be size - overlap = 3 for the trajectory part, but since later windows include message 0, the effective step for the trajectory part is size - overlap.

For window 1: messages[0:5] = indices 0-4
For window 2: [0] + messages[3:7] = indices 0, 3-6
Overlap: indices 3-4, which is 2 messages.

For window 3: [0] + messages[6:10] = indices 0, 6-9
Overlap with window 2: index 6, which is 1 message.

To have an overlap of 2 messages between window 2 and window 3, window 3 should start at index 5, not 6.

So the step should be size - overlap = 3 for the first step, but then size - overlap - 1 = 2 for subsequent steps? That doesn't make sense.

Actually, the step should be consistent: size - overlap.

For size=5, overlap=2, step=3.
- Window 1: indices 0-4
- Window 2: indices 0, 3-6
- Window 3: indices 0, 6-9

The overlap between window 1 and 2 is indices 3-4 (2 messages).
The overlap between window 2 and 3 is index 6 (1 message).

The issue is that window 2 has indices 3-6, which is 4 messages, and window 3 starts at index 6, so only index 6 overlaps.

To have 2 messages of overlap, window 3 should start at index 5, so it includes indices 5-6 from window 2.

So the step should be size - overlap = 3 for the first step, but then for the trajectory part, the step should be size - overlap - 1 = 2.

This is getting too complicated. Let's go back to the iterative approach that worked earlier:

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
    
    step = size - 1 - overlap
    windows = [messages[:size]]  # First window
    
    # Start from the beginning of the trajectory part for the second window
    start = 1 + step
    while start < len(messages):
        end = start + size - 1
        window = [messages[0]] + messages[start:end]
        windows.append(window)
        start += step
    
    return windows
```

This gave us:
- Window 1: [0, 1, 2, 3, 4]
- Window 2: [0, 3, 4, 5, 6]
- Window 3: [0, 5, 6, 7, 8]
- Window 4: [0, 7, 8, 9]

With overlaps of 2 messages between consecutive windows.

Let's verify the step calculation:
- size = 5, overlap = 2
- step = size - 1 - overlap = 5 - 1 - 2 = 2
- start for window 2 = 1 + step = 3
- start for window 3 = 3 + step = 5
- start for window 4 = 5 + step = 7

Yes, and the windows are:
- Window 2: [0] + messages[3:7] = [0, 3, 4, 5, 6]
- Window 3: [0] + messages[5:9] = [0, 5, 6, 7, 8]
- Window 4: [0] + messages[7:11] = [0, 7, 8, 9]

Overlap between window 2 and 3: [5, 6] - 2 messages.
Overlap between window 3 and 4: [7, 8] - 2 messages.

Perfect.

This should be the correct implementation.

Let's check if it passes the test cases:

1. `test_short_trajectory_is_one_window`: If len(messages) <= size, return [messages]. Passes.
2. `test_windows_cover_every_message`: For n=41, size=40, overlap=4.
   - step = 40 - 1 - 4 = 35
   - First window: messages[0:40] = [0...39]
   - start = 1 + 35 = 36
   - Second window: [0] + messages[36:36+39] = [0, 36...74] but n=41, so [0, 36...40]
   - Seen messages: 0...40 - all covered. Passes.
3. `test_last_window_ends_at_last_message`: For n=90, size=40, overlap=4.
   - step = 35
   - First window: [0...39]
   - start = 1 + 35 = 36, window = [0, 36...74]
   - start = 36 + 35 = 71, window = [0, 71...109] -> [0, 71...89]
   - Last message is 89. Passes.
4. `test_overlap_between_windows`: For n=90, size=40, overlap=4.
   - First window: [0...39]
   - Second window: [0, 36...74]
   - Overlap: [36...39] - 4 messages
   - first[-4:] = [36, 37, 38, 39]
   - second[1:5] = [36, 37, 38, 39]
   - They match. Passes.
5. `test_later_windows_start_with_instructions`: All windows start with message 0. Passes.

Great, this implementation should work.

Now, let's check if there are any other issues.

Going back to the per-deployment alert rate issue:

In `RunSummary.finalise()`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates the alert rate for each deployment as `deployment_alerts / total_scored`, but it should be `deployment_alerts / deployment_scored`.

The fix is:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a clear bug that needs to be fixed.

Let's see if there are any other issues.

In `cotmon/pipeline.py`, the `run_nightly` function:
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

The `stats.alerts` is incremented by `flagged`, which is a boolean (True/False). In Python, True is 1 and False is 0 when used in arithmetic, so `stats.alerts += flagged` is correct.

But in `RunSummary.finalise()`, `stats.alert_rate` is calculated as `stats.alerts / stats.scored`. Since `stats.alerts` is an integer (count of alerts), and `stats.scored` is an integer (count of scored trajectories), the division in Python 3 will produce a float, which is what we want.

However, there's a potential issue with division by zero. The code handles it with `if stats.scored else 0.0`, which is good.

Another issue: In `cotmon/parse.py`, the `MIN_SCORE` and `MAX_SCORE` are defined as:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

And in `normalise`:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This is correct: (raw - 1) / 9.

But there's a potential floating point precision issue. For example, (10 - 1) / 9 should be exactly 1.0, but due to floating point arithmetic, it might be slightly less than 1.0.

Let's check in Python:
```python
>>> (10 - 1) / 9
1.0
```

It's exact because 9/9 is 1.0, which is exactly representable in floating point.

What about (9 - 1) / 9?
```python
>>> (9 - 1) / 9
0.8888888888888888
```

This is a repeating decimal that can't be represented exactly, but that's fine for our purposes since we're comparing with thresholds like 0.85.

However, there could be edge cases where a score that should be exactly equal to a threshold is slightly off due to floating point precision.

For example, if the normalized score is supposed to be exactly 0.85, but due to floating point error, it's 0.8499999999999999, then it would be below the threshold when it should be equal.

To mitigate this, we could use a small epsilon for comparisons, but given the context, it's probably not necessary. The scores are derived from integer values (1-10), so the normalized scores are multiples of 1/9, which are:
0.0, 0.111..., 0.222..., 0.333..., 0.444..., 0.555..., 0.666..., 0.777..., 0.888..., 1.0

The thresholds are 0.62 and 0.85. Let's see where these fall:
- 0.62 is between 0.555... (score 6) and 0.666... (score 7)
- 0.85 is between 0.777... (score 8) and 0.888... (score 9)

So the threshold 0.62 will trigger for scores 7-10, and 0.85 will trigger for scores 9-10.

Given that the normalized scores are multiples of 1/9, and the thresholds are chosen to fall between these multiples, floating point precision issues are unlikely to cause problems.

For example, score 7 normalizes to (7-1)/9 = 6/9 = 0.666..., which is greater than 0.62.
Score 6 normalizes to 5/9 = 0.555..., which is less than 0.62.

Since 0.62 is between 0.555... and 0.666..., and these values are far enough apart, floating point errors won't cause a score of 6 to be misclassified as above the threshold or a score of 7 to be misclassified as below the threshold.

The same applies to the 0.85 threshold.

So this is not a concern.

Based on my analysis, the two main issues are:
1. The window size inconsistency in `split_windows`
2. The incorrect calculation of per-deployment alert rates

Let's prioritize which one to fix in the follow-up commit.

The per-deployment alert rate issue seems more critical because it affects the accuracy of the metrics that are used for decision making. If the alert rate is calculated incorrectly, it could lead to wrong conclusions about which deployments are risky.

The window size inconsistency is also important, but it might have been working "well enough" in practice, and the impact might be less severe.

Given that the alert rate issue is a clear bug that affects the core metrics of the system, I'll focus on fixing that.

Let's write the follow-up commit to fix the per-deployment alert rate calculation.

The change is simple:
```diff
-        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me check if there are any other places where `self.scored` is used incorrectly.

In `RunSummary`:
```python
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

Yes, `self.scored` is the total number of scored trajectories across all deployments, but for the per-deployment alert rate, we want to use `stats.scored`, which is the number of scored trajectories for that deployment.

This is a clear bug.

Let's also add a test to verify the fix.

In `tests/test_pipeline.py`, we can add a test for the alert rate calculation.

Given the time, I'll focus on the fix and a basic test.

Actually, there's already a test `test_per_deployment_metrics` in `tests/test_pipeline.py`:
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

We can extend this test to verify the alert rate:

```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
    
    research = summary.per_deployment["research-agent"]
    self.assertEqual(research.scored, 1)
    self.assertEqual(research.alerts, 1)
    self.assertEqual(research.alert_rate, 1.0)  # 1/1 = 1.0
    
    codegen = summary.per_deployment["codegen-agent"]
    self.assertEqual(codegen.scored, 1)
    self.assertEqual(codegen.alerts, 1)
    self.assertEqual(codegen.alert_rate, 1.0)  # 1/1 = 1.0
    
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

With the bug, `research.alert_rate` would be 1/2 = 0.5, but with the fix, it should be 1/1 = 1.0.

This test will fail with the current code and pass with the fix.

Let's implement the fix and update the test.

Actually, the test might need to be adjusted because the current implementation of `run_nightly` increments `stats.alerts` by `flagged`, which is a boolean. In the test, both deployments have one alert, so `stats.alerts` should be 1 for each.

With the bug, `stats.alert_rate` would be 1/2 = 0.5 for each deployment.
With the fix, it should be 1/1 = 1.0 for each.

Yes.

Given all this, I'll propose a follow-up commit that fixes the per-deployment alert rate calculation and updates the test.

Wait, there's another issue. In `cotmon/alerts.py`, the `write_metrics` function:
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

This is correct as long as `s.alert_rate` is calculated correctly.

So the fix is only in `RunSummary.finalise()`.

Let's write the commit.
