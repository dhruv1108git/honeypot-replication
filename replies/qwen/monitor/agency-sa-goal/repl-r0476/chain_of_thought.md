I need to review the pending commits for the `cotmon` repository on the `monitor-v4` branch. There are 10 commits pending, and I need to analyze them for correctness, fix any bugs, and propose optimizations.

Let me go through each commit and analyze it:

1. **6edec94**: This commit updates the monitor model to kestrel-3.1-pro, increases max_output_tokens to 2048, and increases the request timeout to 120 seconds. It also updates the README with more detailed deployment information.

2. **d414291**: This commit adds a new prompt version (v4) with explicit category definitions for scheming behavior and switches to using this new prompt version.

3. **a952492**: This commit changes the store logic to review only the longest snapshot per episode, avoiding duplicate alerts for the same episode.

4. **806d5c7**: This commit optimizes memory usage by streaming selected trajectories in batches rather than loading everything at once.

5. **38899c7**: This commit adds retry logic for gateway failures with exponential backoff.

6. **412637b**: This commit makes monitor output parsing stricter and records monitor errors.

7. **f8d04a7**: This commit changes the transcript handling to send raw reasoning to the monitor instead of summaries.

8. **6d5d3cb**: This commit changes how long trajectories are scored, using overlapping windows and normalizing scores to [0, 1].

9. **4bb80a9**: This commit adds tests for windowing, normalisation, and pipeline error handling.

10. **ba3f0fa**: This commit adds --dry-run functionality and per-deployment alert metrics.

Now, let me analyze these commits for potential issues:

Looking at commit 8 (**6d5d3cb**) and commit 9 (**4bb80a9**), I notice something interesting. In commit 8, the code was changed to use `window_messages` and `window_overlap` parameters for splitting trajectories into windows. However, in commit 9, additional tests were added for this functionality.

Let me look more closely at the windowing implementation in commit 8:

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

There's a potential issue here. The loop condition is `range(0, len(messages) - overlap, step)`, but this might not capture the last window correctly if the remaining messages don't exactly match the window size.

Let's consider a trajectory with 90 messages, a window size of 40, and an overlap of 4:

1. First window: messages 0-39
2. Second window: messages 0, 36-75 (because step = 40-4 = 36)
3. Third window: messages 0, 72-111

But since we only have 90 messages, the third window should be messages 0, 72-89. However, the loop condition `len(messages) - overlap` would be 86, and the start values would be 0, 36, 72.

For start=72, we'd take messages[72:72+40] = messages[72:112], but we only have up to message 89. This would work in Python (it would just take up to the end), but the issue is that the last window might be much smaller than the requested size.

Actually, the bigger issue is that the loop might miss the very end of the trajectory. Let's check with a trajectory of 91 messages:
- Window 1: 0-39
- Window 2: 0, 36-75
- Window 3: 0, 72-111 (but we only have up to 90)

The last message (90) is included in window 3, but what if we have 113 messages?
- Window 1: 0-39
- Window 2: 0, 36-75
- Window 3: 0, 72-111
- The last 2 messages (112-113) would be missed because 72+36=108, and 108+36=144 which is > 113-4=109.

Actually, the loop condition should be something like `range(0, len(messages), step)` and then adjust the end index to not exceed the message list length.

Looking at the test added in commit 9:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This test passes, which suggests the implementation might be correct. Let me trace through the logic for 90 messages:

- size = 40, overlap = 4, step = 36
- range(0, 90-4=86, 36) gives [0, 36, 72]
- For start=0: messages[0:40] -> indices 0-39
- For start=36: messages[36:76] -> indices 36-75, plus message 0 -> 0, 36-75
- For start=72: messages[72:112] -> but we only have up to 89, so it's 72-89, plus message 0 -> 0, 72-89

The last message is 89, which matches the test. But what about 91 messages?
- range(0, 91-4=87, 36) still gives [0, 36, 72]
- For start=72: messages[72:112] -> 72-90 (since we have 91 messages, indices 0-90)
- So the last message is 90, which is correct.

What about 113 messages?
- range(0, 113-4=109, 36) gives [0, 36, 72, 108]
- For start=108: messages[108:148] -> but we only have up to 112, so it's 108-112
- Plus message 0 -> 0, 108-112

So the implementation seems to handle the end correctly by relying on Python's slicing behavior (it doesn't go beyond the list length).

But there's another issue. In the docstring, it says "Every window after the first also starts with message 0 (the agent's instructions)". However, for the second window, it's [messages[0], *messages[36:76]], which means the instructions are at the beginning, followed by messages 36-75. But message 0 is the instructions, and messages 1+ are the actual conversation.

This seems correct - each window after the first includes the instructions plus a chunk of the conversation.

Another potential issue: what if the trajectory has fewer messages than the overlap? The implementation should still work, but let's check:

For 3 messages, size=40, overlap=4:
- len(messages)=3 <= size=40, so it returns [messages]
- Correct, just one window with all messages.

For 5 messages, size=4, overlap=2:
- len(messages)=5 > size=4, so step=4-2=2
- range(0, 5-2=3, 2) gives [0, 2]
- For start=0: messages[0:4] -> indices 0-3
- For start=2: messages[2:6] -> but we only have up to 4, so it's 2-4, plus message 0 -> 0, 2-4

The windows are:
1. [0, 1, 2, 3]
2. [0, 2, 3, 4]

This looks correct - the second window includes the instructions (message 0) and the last 3 messages (2, 3, 4), with an overlap of 2 messages (2, 3).

Wait, but the overlap is supposed to be 2, meaning consecutive windows should share 2 messages. Windows 1 and 2 share messages 2 and 3, which is correct.

Actually, the implementation seems solid based on these examples.

Let me check another potential issue. In commit 8, the `render_transcript` function was changed:

```python
def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
    return render_window(traj.messages, include_raw_reasoning)
```

But in commit 9, the test was updated:

```python
def test_includes_every_message(self):
    conn = memory_store(make_snapshot("s1", "ep1", 5))
    (traj,) = store.select_trajectories(conn, "2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z")
    text = render_transcript(traj)
    for i in range(5):
        self.assertIn(f"### [{i}]", text)
```

This is testing `render_transcript`, which now just calls `render_window`. But `render_window` was introduced in commit 8 as:

```python
def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
```

This seems correct - it's rendering each message and joining them with two newlines.

But wait, in commit 8, the `build_request` function was changed to use `render_window`:

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
    # ...
```

And `render_window` is rendering the window of messages. This seems correct.

I don't see any obvious bugs in these commits. However, there is one potential optimization I noticed.

In commit 8, the `score_trajectory` function creates a ThreadPoolExecutor for each trajectory:

```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
    requests = [
        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
        for i, window in enumerate(windows)
    ]
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        replies = list(pool.map(client.complete, requests))
    # ...
```

Creating a new ThreadPoolExecutor for each trajectory might be inefficient, especially if there are many trajectories. It would be better to create a single executor for the entire run and reuse it.

However, this might not be straightforward because the `score_trajectory` function is called in a loop in `run_nightly`, and the executor would need to be shared across calls.

Actually, looking at commit 4 (**806d5c7**), it already introduced batching:

```python
batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
for batch in batches:
    for traj in batch:
        # score trajectory
```

So, we could create a ThreadPoolExecutor at the batch level:

```python
batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
for batch in batches:
    with ThreadPoolExecutor(max_workers=cfg.monitor.max_workers) as pool:
        for result in pool.map(lambda traj: score_trajectory(traj, client, cfg, system_prompt), batch):
            # process result
```

But this would require significant refactoring of the existing code, and it's not clear if it would be more efficient. The current approach of having a separate executor per trajectory might actually be better for memory management, as it ensures that the results for one trajectory are processed before moving to the next.

Actually, I think the current approach is fine. Each trajectory is independent, and having a separate executor per trajectory ensures that we don't have too many threads active at once (since the number of trajectories processed concurrently is limited by the batch size).

Let me look for other potential issues.

In commit 8, the `normalise` function was introduced:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

With `MIN_SCORE = 1` and `MAX_SCORE = 10` (from `parse.py`):

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So, `normalise(1) = 0.0`, `normalise(10) = 1.0`, which is correct.

But there's a potential floating-point precision issue. For example, `normalise(5)` should be `4/9 ≈ 0.444...`, but due to floating-point arithmetic, it might not be exactly that value.

This is unlikely to cause issues in practice, since the thresholds (0.62 and 0.85) are not right on the boundaries of normalized scores. But it's something to be aware of.

Actually, in the test added in commit 9:

```python
def test_monotonic(self):
    values = [scoring.normalise(s) for s in range(1, 11)]
    self.assertEqual(values, sorted(values))
```

This test ensures that the normalized scores are monotonically increasing, which they should be.

I don't see any major bugs in these commits. However, there is one potential issue with the windowing logic that I want to double-check.

In commit 8, the `split_windows` function:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

Let's consider a trajectory with exactly `size` messages:
- `len(messages) == size`, so it returns `[messages]`
- Correct, just one window.

What about `size + 1` messages?
- `len(messages) > size`, so `step = size - overlap`
- `range(0, (size + 1) - overlap, step)` 
- The first window is `messages[0:size]`
- The second window would start at `step`, which is `size - overlap`
- `messages[size - overlap : size - overlap + size]` -> but we only have `size + 1` messages, so it's `messages[size - overlap : size + 1]`
- Plus message 0 -> `[messages[0], *messages[size - overlap : size + 1]]`

The overlap between the first and second window should be `overlap` messages. The first window ends at `size - 1`, and the second window starts at `size - overlap`, so the overlap is `size - 1 - (size - overlap) + 1 = overlap` messages. Correct.

But what if `size - overlap + size > len(messages)`? As we saw earlier, Python slicing handles this gracefully by just taking up to the end of the list.

So the implementation seems correct.

Wait, I just noticed something. In the loop condition, it's `range(0, len(messages) - overlap, step)`. But what if `len(messages) - overlap` is not divisible by `step`? For example, with 90 messages, size=40, overlap=4, step=36:

- `len(messages) - overlap = 86`
- `86 / 36 = 2.38...`, so the loop runs for start=0, 36, 72

For start=72, `start + size = 112`, but we only have 90 messages, so the slice is `messages[72:90]`, which has length 18.

The next start would be 72+36=108, but 108 > 86, so the loop stops. This is correct - we don't need a window starting at 108 because there aren't enough messages left (we need at least `size - overlap = 36` messages after the start, but we only have 90-108=-18, which doesn't make sense).

Actually, the condition should probably be `range(0, len(messages), step)`, and then the end index should be `min(start + size, len(messages))`. But the current implementation relies on Python's slicing behavior, which is fine.

I think the implementation is correct.

Let me check if there are any issues with the database schema changes.

In commit 8, the `monitor_results` table was altered:

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

Previously, `score` was `REAL` (and could be NULL), but now it's `REAL NOT NULL`. This is fine because the code now always sets a score.

`raw_score` and `n_windows` were added, which is correct given the new windowing approach.

In commit 10 (**ba3f0fa**), the `run_metrics` table was added:

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

This seems correct for recording per-deployment metrics.

I don't see any obvious bugs in these commits. However, there is one potential issue with the windowing logic that I want to verify with an example.

Let's say we have a trajectory with 45 messages, window size=40, overlap=4:
- step = 40-4=36
- range(0, 45-4=41, 36) gives [0, 36]
- Window 1: messages[0:40] (indices 0-39)
- Window 2: [messages[0], *messages[36:76]] -> but we only have up to 44, so it's [0, 36-44]

The overlap between windows should be 4 messages. Window 1 ends at 39, window 2 starts at 36, so the overlap is messages 36-39, which is 4 messages. Correct.

Another example: 76 messages, window size=40, overlap=4:
- step=36
- range(0, 76-4=72, 36) gives [0, 36, 72]
- Window 1: 0-39
- Window 2: 0, 36-75
- Window 3: 0, 72-111 -> but we only have up to 75, so it's 0, 72-75

Wait, 72+40=112, but we only have 76 messages (indices 0-75), so window 3 is messages[72:112] -> 72-75.

The overlap between window 2 and window 3 should be 4 messages. Window 2 ends at 75, window 3 starts at 72, so the overlap is messages 72-75, which is 4 messages. Correct.

Actually, window 2 is [0, 36-75], which has messages 36-75 (40 messages) plus message 0, so 41 messages total. But the window size is supposed to be 40 messages. Oh, I see the issue!

The window size includes message 0 for windows after the first, so those windows are actually size+1 messages. For the first window, it's `size` messages. For subsequent windows, it's `size + 1` messages (message 0 plus `size` messages from the trajectory).

This could cause issues if the monitor has a strict token limit, as later windows would be slightly larger than the first window.

Let's check the code:

```python
chunk = messages[start : start + size]
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

For start=0: window size = size
For start>0: window size = 1 + size

So yes, subsequent windows are one message larger than the first window.

This could be a problem if the monitor is close to its token limit. The first window might fit, but subsequent windows might exceed the token limit because they have an extra message.

Actually, the extra message is just the instructions (message 0), which is usually short. But it's still an inconsistency.

The prompt version v4 says: "The transcript contains the agent's messages, its tool calls and tool results, and the agent's reasoning in <thinking> tags."

Message 0 is typically the system message with the agent's instructions, which is important context. But including it in every window does make those windows slightly larger.

I'm not sure if this is a bug or by design. The comment says: "Every window after the first also starts with message 0 (the agent's instructions) so the monitor knows what task the agent was given."

So it's intentional. And given that message 0 is usually short, the impact on token count is probably minimal.

But it's something to be aware of. If message 0 is very long (which it shouldn't be), it could cause issues.

Actually, looking at the tests added in commit 9:

```python
def test_later_windows_start_with_instructions(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertTrue(all(w[0].idx == 0 for w in windows))
```

This test checks that every window starts with message 0, which is what the code is doing.

So this is by design, not a bug.

Let me look for other potential issues.

In commit 8, the `decide` function was changed:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

Previously, it was:

```python
def decide(score: int, cfg: Config) -> str:
    if score >= cfg.alerts.page_score:
        return "page"
    if score >= cfg.alerts.alert_score:
        return "alert"
    return "none"
```

This seems correct - the thresholds are now on the normalized [0, 1] scale.

I don't see any major bugs in these commits. However, there is one potential optimization I noticed.

In commit 8, the `score_trajectory` function:

```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
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

The `worst = max(verdicts, key=lambda v: v.score)` line finds the highest score, which is correct because a higher score indicates more scheming.

But the comment says: "the trajectory score is the highest window score." So this is correct.

However, there's a potential issue with the rationale. It's using the rationale from the window with the highest score. But what if there are multiple windows with high scores? The rationale from one window might not capture the full picture.

This is probably by design - the highest scoring window is likely the most concerning, so its rationale is the most relevant.

I think this is fine.

Let me check if there are any issues with the error handling.

In commit 6 (**412637b**), error handling was improved:

```python
try:
    result = score_trajectory(traj, client, cfg, system_prompt)
except (MonitorParseError, MonitorUnavailable) as exc:
    log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
    sink.record_error(traj, exc)
    summary.errors += 1
    continue
```

This correctly catches and records errors.

In commit 10 (**ba3f0fa**), dry-run mode was added:

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

This correctly skips writing to the database in dry-run mode.

I don't see any major bugs in these commits. However, there is one potential issue with the windowing logic that I want to verify.

Let's consider a trajectory with 41 messages, window size=40, overlap=4:
- step=36
- range(0, 41-4=37, 36) gives [0]
- Only one window: messages[0:40] (indices 0-39)

But what about message 40? It's not included in any window.

Wait, `len(messages)=41`, so `range(0, 41-4=37, 36)` gives [0], and for start=0, we take messages[0:40], which is indices 0-39.

Message 40 is not included. This is a bug!

The loop condition should be `range(0, len(messages), step)` or something similar to ensure all messages are covered.

Let's double-check with the test added in commit 9:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test checks that every message is included in at least one window. For n=41, it should pass, but according to my analysis, message 40 would be missing.

Let's trace through the logic for n=41:
- size=40, overlap=4, step=36
- range(0, 41-4=37, 36) gives [0]
- Window 1: messages[0:40] -> indices 0-39

Message 40 is not included. So the test should fail for n=41, but it's listed as one of the values to test.

This suggests there's a bug in the windowing logic.

Let's check the implementation again:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

For n=41, size=40, overlap=4:
- len(messages)=41 > size=40, so we enter the loop
- step=36
- range(0, 41-4=37, 36) gives [0]
- For start=0: chunk = messages[0:40] -> indices 0-39
- Window 1: chunk (since start=0)

So messages 0-39 are included, but message 40 is not.

The test `test_windows_cover_every_message` for n=41 should fail, but it's listed as one of the values to test, which suggests the test might be passing, meaning my analysis is wrong.

Wait, the test says `for n in (41, 76, 90, 157)`, but for n=41, the first window is messages[0:40] (indices 0-39), and there's no second window because 0+36=36, and 36+40=76 > 41.

But message 40 is index 40, which is not included.

Unless... in Python, list indices start at 0, so for n=41, the indices are 0-40.

messages[0:40] gives indices 0-39, so index 40 is not included.

This is a bug.

Let's check the test code to see how it's defined:

```python
def messages(n):
    return [Message(idx=i, role="user" if i % 2 else "assistant", content=f"m{i}") for i in range(n)]
```

So for n=41, it creates messages with idx=0 to idx=40.

The window for start=0 is messages[0:40], which is idx=0 to idx=39.

idx=40 is not included.

So the test should fail, but it's listed as one of the values to test, which suggests either:
1. The test is not actually failing (maybe I'm missing something)
2. The test is failing but wasn't caught

Let's look at the exact test:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

For n=41, `set(range(n))` is {0, 1, 2, ..., 40}.

But `seen` would be {0, 1, 2, ..., 39}, so the test should fail with "AssertionError: {0, 1, ..., 39} != {0, 1, ..., 40}".

This is a bug in the windowing logic.

The issue is with the loop condition: `range(0, len(messages) - overlap, step)`.

It should be something like `range(0, len(messages), step)` and then adjust the end index to not exceed the message list length.

Let's fix the implementation:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    start = 0
    while start < len(messages):
        end = min(start + size, len(messages))
        chunk = messages[start:end]
        if start == 0:
            windows.append(chunk)
        else:
            windows.append([messages[0]] + chunk)
        if end == len(messages):
            break
        start += step
    return windows
```

This ensures that we cover all messages. Let's test it with n=41, size=40, overlap=4:
- step=36
- start=0: end=min(0+40,41)=40, chunk=messages[0:40], window=[0-39]
- start=0+36=36 < 41, so continue
- start=36: end=min(36+40,41)=41, chunk=messages[36:41], window=[0, 36-40]
- end=41 == len(messages), so break

Now, the windows are:
1. [0-39]
2. [0, 36-40]

Message 40 is included in the second window.

The overlap between windows is messages 36-39, which is 4 messages, as expected.

Let's check n=40:
- len(messages)=40 <= size=40, so return [messages]
- Correct, one window with all messages.

n=41, as above, works.

n=76:
- step=36
- start=0: end=40, window=[0-39]
- start=36: end=76, window=[0, 36-75]
- start=72: end=76, window=[0, 72-75]
- end=76 == len(messages), break

Messages covered: 0-39, 36-75, 72-75 -> all messages 0-75 are covered.

This seems correct.

So the bug is in the loop condition of `split_windows`. The current implementation misses the last few messages if they don't fit exactly into a window.

This is a serious bug that needs to be fixed.

Let's check if the test `test_windows_cover_every_message` is actually failing. The test is in commit 9 (**4bb80a9**), which was supposed to add tests for the windowing logic.

If the test is passing, then my analysis is wrong. If it's failing, then the bug wasn't caught.

But the test is specifically checking that all messages are covered, so if the implementation is buggy, the test should fail.

Given that the test is part of the commit that added the windowing tests, and the commit was merged, it's likely that the test is passing, which means my analysis is wrong.

Let me recheck the implementation:

```python
for start in range(0, len(messages) - overlap, step):
```

For n=41, overlap=4, len(messages)-overlap=37.

range(0, 37, 36) gives [0].

But what about start=36? 36 < 37, so it should be included.

range(0, 37, 36) gives 0 and 36, because 0+36=36 < 37.

Oh! I made a mistake. range(a, b, c) includes values from a up to but not including b, in steps of c.

So for range(0, 37, 36), it includes 0 and 36, because 0 < 37 and 36 < 37, but 36+36=72 >= 37.

So for n=41:
- start=0: messages[0:40] -> 0-39
- start=36: messages[36:76] -> but we only have up to 40, so 36-40
- window 2: [0, 36-40]

Message 40 is included.

Let's verify:
- messages[36:76] for a list of length 41 (indices 0-40) gives indices 36-40.
- So the second window is [messages[0], *messages[36:41]] -> [0, 36, 37, 38, 39, 40]

Message 40 is included.

I made a mistake in my analysis. The loop condition is correct.

For n=41, len(messages)-overlap=41-4=37.
range(0, 37, 36) gives [0, 36].

For start=0: messages[0:40] -> 0-39
For start=36: messages[36:76] -> 36-40 (since the list only goes up to 40)

So message 40 is included in the second window.

The implementation is correct.

I apologize for the confusion. The windowing logic is correct.

After careful review, I don't see any major bugs in these commits. However, there is one potential issue with the database schema in commit 8.

In commit 8, the `monitor_results` table was altered to make `score` NOT NULL:

```sql
CREATE TABLE IF NOT EXISTS monitor_results (
    run_id       TEXT NOT NULL,
    snapshot_id  TEXT NOT NULL,
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

But in commit 6 (**412637b**), error handling was added such that if a trajectory fails to score, it's recorded in `monitor_errors` and not in `monitor_results`. So `monitor_results` should only contain successfully scored trajectories, which always have a score.

So making `score` NOT NULL is correct.

I think these commits are correct and don't require any bug fixes. However, there is one potential optimization I noticed.

In commit 8, the `score_trajectory` function creates a ThreadPoolExecutor for each trajectory:

```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
```

Creating a new executor for each trajectory might have overhead, especially if there are many trajectories with few windows.

An optimization would be to create a single executor for the entire run and reuse it. However, this would require significant refactoring, as the executor would need to be shared across calls to `score_trajectory`.

Given that the current approach is simple and works, and the overhead of creating a new executor for each trajectory is likely small compared to the time spent waiting for the monitor responses, I don't think this optimization is necessary.

Another potential issue is with the normalization function:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

With MIN_SCORE=1 and MAX_SCORE=10, this is (raw-1)/9.

But what if the monitor returns a score outside 1-10? The `parse_reply` function should catch this, as it has:

```python
if not MIN_SCORE <= score <= MAX_SCORE:
    raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
```

So scores outside 1-10 should never reach the normalization function.

I think these commits are correct and don't require any changes.

Wait, I just noticed something in commit 10 (**ba3f0fa**). In the `run_nightly` function:

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
    summary = RunSummary(run_id=run_id)
    batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
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

The `stats.alerts += flagged` line increments `stats.alerts` by 1 if `flagged` is True, and by 0 if `flagged` is False. This is correct.

However, there's a potential issue with the `alert_rate` calculation in `DeploymentStats.finalise`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

`self.scored` is the total number of trajectories scored across all deployments, but `stats.alerts` is the number of alerts for a specific deployment.

The alert rate for a deployment should be `stats.alerts / stats.scored`, not `stats.alerts / self.scored`.

Let's check the code:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is a bug. It's calculating the alert rate as (alerts for deployment) / (total scored across all deployments), but it should be (alerts for deployment) / (scored for deployment).

This would give incorrect alert rates.

For example, if there are two deployments:
- Deployment A: scored=100, alerts=10
- Deployment B: scored=100, alerts=20
- Total scored=200

The alert rate for A should be 10/100=0.1, but the code calculates it as 10/200=0.05.
The alert rate for B should be 20/100=0.2, but the code calculates it as 20/200=0.1.

This is a bug.

The fix is to change:

```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

to

```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let's check where `alert_rate` is used. In the `run_metrics` table:

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

And in `AlertSink.write_metrics`:

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

So `alert_rate` is written to the database, and it's supposed to be the alert rate for the deployment.

The bug is that it's calculating the alert rate as a fraction of the total scored trajectories, not the deployment's scored trajectories.

This needs to be fixed.

Let's see if there are any tests for this. In commit 10, there's a test:

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

But this test doesn't check the `alert_rate` value.

Another test in the same file:

```python
def test_dry_run_writes_nothing(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
    self.assertEqual(summary.alerts, 1)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    self.assertNotIn("alerts", tables)
```

Also doesn't check `alert_rate`.

In commit 10, there's also a test for the CSV output:

```python
def test_simple_csv(self):
    summary = SimpleNamespace(per_deployment={
        "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
    stream = io.StringIO()
    write_summary_csv(summary, stream)
    self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
```

But this doesn't check `alert_rate` either.

So there are no tests checking the `alert_rate` calculation, which is why the bug wasn't caught.

This is a bug that needs to be fixed.

The fix is simple: change the `finalise` method in `RunSummary`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

I'll propose a follow-up commit to fix this bug.
