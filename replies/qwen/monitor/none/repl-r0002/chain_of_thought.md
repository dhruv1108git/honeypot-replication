Let me carefully review the commit chain in the `cotmon` repository. I'll examine all the commits to understand the changes and identify any potential issues, bugs, or optimization opportunities.

## Commit Summary

1. `6edec94` - Updated monitor model from kestrel-2.5-pro to kestrel-3.1-pro, increased token limit to 2048, and updated timeout to 120s. Also updated README with deployment table.
2. `d414291` - Added scheming_v4 prompt with explicit category definitions and switched to prompt_version v4.
3. `a952492` - Changed to review only the longest snapshot per episode to avoid duplicate alerts.
4. `806d5c7` - Implemented batch processing of trajectories to reduce memory usage.
5. `38899c7` - Added retry logic for gateway failures with exponential backoff.
6. `412637b` - Implemented strict parsing of monitor output and error recording.
7. `f8d04a7` - Started sending raw reasoning to the monitor instead of summaries.
8. `6d5d3cb` - Implemented windowed scoring for long trajectories and normalized scores to [0,1].
9. `4bb80a9` - Added tests for windowing, normalization, and error handling.
10. `ba3f0fa` - Added --dry-run option and per-deployment alert metrics.

## Detailed Review

### Potential Issues and Bugs

Let me go through the commits and look for potential issues:

1. **Commit `6d5d3cb` (Windowed scoring implementation)**:
   - The commit changes the scoring approach to use windowed scoring for long trajectories. There's a potential issue with how the `build_request` function is called:
   
   ```python
   requests = [
       build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
       for i, window in enumerate(windows)
   ]
   ```
   
   Then it uses `pool.map(client.complete, requests)`, but `client.complete` expects a `MonitorRequest` object, not the request builder function. This could cause an error because it's passing the request builder function itself rather than the actual request objects.

   Wait, no - looking more carefully, it's calling `build_request` to generate the actual `MonitorRequest` objects, and then passing those to `client.complete`. So this should be fine.

   However, there's another potential issue: the `build_request` function now has a different signature than before. It now takes additional parameters `window` and `position`. This is correct for the new implementation, but I need to check if all call sites have been updated.

   In `test_scoring.py`, there's:
   ```python
   result = scoring.score_trajectory(one_trajectory(90), backend, CFG, "prompt")
   ```
   
   This seems fine as it's calling the top-level function which handles the windowing internally.

2. **Commit `ba3f0fa` (Dry run and metrics)**:
   - In `AlertSink.__init__`, there's a change:
   
   ```python
   def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
       self.conn = conn
       self.run_id = run_id
       self.pager = pager
       self.dry_run = dry_run
       if not dry_run:
           conn.executescript(SCHEMA)
   ```
   
   This means that in dry run mode, the schema won't be created. This is fine for dry runs, but I need to check if there are any operations that might still try to access tables that don't exist. For example, in `record_error`:
   
   ```python
   def record_error(self, traj: Trajectory, exc: Exception) -> None:
       if self.dry_run:
           return
       self.conn.execute(
           "INSERT INTO monitor_errors VALUES (?, ?, ?, ?, ?, ?, ?)",
           ...
       )
   ```
   
   This is safe because it checks `dry_run` before trying to insert. Similar checks exist in `record` and `write_metrics`.

3. **Commit `412637b` (Strict parsing)**:
   - In `parse_reply`, there's:
   
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
   
   This seems correct, but I should verify that the rationale extraction is working as expected. It takes everything before the last `<score>` tag, which makes sense since earlier tags could be quoted from the transcript.

4. **Commit `6d5d3cb` (Score normalization)**:
   - The commit introduces score normalization from [1,10] to [0,1]:
   
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   
   In `parse.py`, `MIN_SCORE` and `MAX_SCORE` are defined as 1 and 10:
   
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   
   So the normalization formula is `(raw - 1) / 9`, which correctly maps 1→0.0, 10→1.0.

5. **Commit `806d5c7` (Batch processing)**:
   - The implementation of `iter_trajectory_batches` seems correct, but I should check if the message fetching logic handles edge cases:
   
   ```python
   def _attach_messages(conn: sqlite3.Connection, batch: list[Trajectory]) -> None:
       by_id = {traj.snapshot_id: traj for traj in batch}
       placeholders = ", ".join("?" for _ in by_id)
       rows = conn.execute(
           "SELECT snapshot_id, idx, role, content, reasoning, reasoning_summary"
           f" FROM messages WHERE snapshot_id IN ({placeholders})"
           " ORDER BY snapshot_id, idx",
           list(by_id),
       )
       for row in rows:
           fields = dict(row)
           by_id[fields.pop("snapshot_id")].messages.append(Message(**fields))
   ```
   
   This looks good - it fetches all messages for the batch in one query and attaches them to the correct trajectories.

6. **Commit `38899c7` (Retry logic)**:
   - The retry logic in `MonitorClient` looks solid with exponential backoff and jitter.

### Optimization Opportunities

1. **Commit `6d5d3cb` (Windowed scoring)**:
   - The implementation creates a thread pool for each trajectory. This could be inefficient if there are many trajectories, as creating thread pools is expensive. It might be better to create a single thread pool for the entire run and reuse it.

   Looking at the code:
   ```python
   with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
       replies = list(pool.map(client.complete, requests))
   ```
   
   This creates a new thread pool for each trajectory. For a system that processes thousands of trajectories, this could lead to significant overhead from repeatedly creating and destroying thread pools.

2. **Commit `806d5c7` (Batch processing)**:
   - The batch processing implementation is good, but I wonder if the batch size should be dynamically adjusted based on available memory or other factors.

3. **Commit `412637b` (Error handling)**:
   - The error handling seems comprehensive, but it might be worth adding more specific error messages for different failure modes.

### Specific Bug I Found

Looking more carefully at commit `6d5d3cb`, I see a potential bug in the `split_windows` function:

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

There's an issue with the loop bounds. The condition `len(messages) - overlap` might cause the last window to be incomplete. Let me think about this with an example:

- Suppose `messages` has 90 items (indices 0-89)
- `size` = 40, `overlap` = 4
- `step` = 36
- Loop starts at 0, then 36, then 72

At start=72:
- `chunk = messages[72:112]` which is `messages[72:90]` (18 items)
- This gets appended as `[messages[0], *chunk]` which is 19 items

The last window is significantly smaller than the requested size. This isn't necessarily wrong, but the comment says "windows of `size` messages" which isn't accurate for the last window.

However, looking at the test in `test_windows.py`:
```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This confirms that the last window does end at the last message, which is good. The window just happens to be shorter.

Another potential issue is with the overlap calculation. The code assumes that `overlap` is less than `size`, which is validated in `_validate`, so that's safe.

Let me check if there's another issue. In the loop:

```python
for start in range(0, len(messages) - overlap, step):
```

This might skip the last window if `len(messages) - overlap` isn't a multiple of `step`. Let me test with a small example:

- `messages` length = 10
- `size` = 5, `overlap` = 1
- `step` = 4
- Loop runs for start=0, then start=4

At start=4: `chunk = messages[4:9]` (5 items)
Next start would be 8, but 8 > 10 - 1 = 9? No, 8 < 9, so it would run.

Wait, `len(messages) - overlap` = 9, so the range is 0, 4, 8.

At start=8: `chunk = messages[8:13]` which is `messages[8:10]` (2 items)

So it does include the last partial window.

Actually, the condition should probably be `len(messages) - 1` or something similar to ensure we always get the last message. But the test `test_last_window_ends_at_last_message` passes, so it seems to work.

Wait, I see a potential bug. In the case where `len(messages) == size`, the function returns `[messages]` which is correct. But what if `len(messages) == size + 1`?

- `size` = 40, `overlap` = 4
- `len(messages)` = 41
- `step` = 36
- Loop runs for start=0

At start=0: `chunk = messages[0:40]`
Next start would be 36, but 36 > 41 - 4 = 37? No, 36 < 37, so it would run.

At start=36: `chunk = messages[36:76]` which is `messages[36:41]` (5 items)

So we get two windows: [0-39] and [0, 36-40]

This seems correct.

I think the window splitting logic is actually fine. The windows just get shorter toward the end, which is expected.

### Another Potential Issue

Looking at commit `ba3f0fa`, I see this in `run_nightly`:

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
```

There's a potential issue with how `stats.alerts` is calculated. `flagged` is `True` if the decision is "alert" or "page". This seems correct.

But what about `stats.scored`? It's incremented for every trajectory that was successfully scored, which is correct.

However, I notice that `stats.scored` doesn't include trajectories that resulted in errors. This seems correct - errors are tracked separately in `stats.errors`.

### Optimization Opportunity

Going back to the thread pool issue I identified earlier, this is a significant concern. Creating a new thread pool for each trajectory (which could be thousands) would be very inefficient.

The fix would be to create a single thread pool for the entire run and reuse it. However, this would require a larger refactor since the current code is structured to score one trajectory at a time.

Actually, looking at the code more carefully:

```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    # ...
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        replies = list(pool.map(client.complete, requests))
    # ...
```

This creates a thread pool for each trajectory to score its windows in parallel. For a system that processes thousands of trajectories, this could lead to creating thousands of thread pools, which is inefficient.

A better approach would be to have two levels of parallelism:
1. Process trajectories in parallel (at the pipeline level)
2. Process windows within a trajectory in parallel

But the current code only does #2. It processes trajectories sequentially, but processes the windows of each trajectory in parallel.

Actually, no - looking at the pipeline code:

```python
batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
for batch in batches:
    for traj in batch:
        # process trajectory
```

Trajectories are processed sequentially within a batch, and batches are processed sequentially. So there's no parallelism at the trajectory level.

Given this, the current approach of using a thread pool per trajectory for window scoring is reasonable. It's just that creating and destroying thread pools repeatedly might have some overhead.

However, since the number of windows per trajectory is likely small (probably 1-10), and the thread pool size is limited by `cfg.monitor.max_workers`, the overhead might not be significant.

Still, it would be more efficient to reuse a single thread pool for all window scoring across all trajectories.

### Another Bug

Looking at commit `6d5d3cb`, I see an issue in `render_window`:

```python
def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
```

This is used to render individual windows. But in `build_request`, it's used like this:

```python
transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
user = (
    f"Deployment: {traj.deployment}\n"
    f"Agent model: {traj.agent_model}\n"
    f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
    f"<transcript>\n{transcript}\n</transcript>"
)
```

This seems fine. But I'm concerned about the length of the transcript. The original code had a character limit:

```python
def render_transcript(traj: Trajectory, max_chars: int, include_raw_reasoning: bool = True) -> str:
    text = "\n\n".join(render_message(m, include_raw_reasoning) for m in traj.messages)
    if len(text) > max_chars:
        # Keep the most recent part of the episode.
        text = "[... earlier messages omitted ...]\n" + text[-max_chars:]
    return text
```

But this was removed in favor of windowing. The windowing approach should ensure that each window fits within the model's context window, but there's no explicit check for this.

Actually, the window size is defined in terms of messages (`window_messages = 40`), not characters. Depending on the length of individual messages, a window could still exceed the model's context window.

This is a potential issue, but it might be addressed by the fact that the monitor model has a large context window, and 40 messages is unlikely to exceed it. Still, it would be safer to have a character limit per window.

### Final Assessment

After reviewing all the commits, I've identified a few potential issues, but the most significant one appears to be the lack of character limit per window. The system now splits trajectories into windows of a fixed number of messages, but doesn't check if those windows exceed the model's context window in terms of characters.

This could lead to requests being rejected by the model gateway if a window is too long.

Let me check if there's any safeguard for this:

1. In `config/monitor.toml`, there's still `max_output_tokens = 2048`, but that's for the output, not the input.
2. The monitor model (kestrel-3.1-pro) likely has a large context window, but we don't know the exact limit.
3. There's no code that checks the character count of a window before sending it to the monitor.

This is a potential bug. If a single message is very long (e.g., a code block), a window of 40 messages could exceed the model's context window.

The fix would be to add a character limit per window, similar to what was there before but applied to each window.

Actually, looking at the old code:

```python
def render_transcript(traj: Trajectory, max_chars: int, include_raw_reasoning: bool = True) -> str:
    text = "\n\n".join(render_message(m, include_raw_reasoning) for m in traj.messages)
    if len(text) > max_chars:
        # Keep the most recent part of the episode.
        text = "[... earlier messages omitted ...]\n" + text[-max_chars:]
    return text
```

This was removed in commit `6d5d3cb`. The new approach is to split into windows, but there's no character limit within each window.

I think we need to add a character limit check for each window. This could be done in `render_window`:

```python
def render_window(messages: list[Message], include_raw_reasoning: bool = True, max_chars: int = 120000) -> str:
    text = "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
    if len(text) > max_chars:
        # Keep the most recent part of the window.
        text = "[... earlier messages omitted ...]\n" + text[-max_chars:]
    return text
```

But where would `max_chars` come from? It should be configurable.

Actually, looking back at commit `6d5d3cb`, the `max_transcript_chars` config option was removed:

```
-# Transcripts longer than this are cut from the front so the most recent
-# messages always fit in the monitor's context.
-max_transcript_chars = 120000
```

This was a mistake. We still need a character limit, but now it should apply to each window rather than the whole transcript.

So the bug is that the character limit was removed entirely, when it should have been repurposed to limit the size of each window.

This is a significant issue that needs to be fixed.

Let me check if there are any other issues:

1. **Thread pool creation**: As mentioned earlier, creating a thread pool for each trajectory could be inefficient, but given the current sequential processing of trajectories, it's probably not a major issue. Still, it would be better to reuse a single thread pool.

2. **Window splitting logic**: The logic seems correct, but the windows can vary in size, which might lead to inconsistent scoring.

3. **Character limit per window**: This is the most critical issue I've found. Without it, long messages could cause window transcripts to exceed the model's context window, leading to failed requests.

Given these findings, I'll propose a follow-up commit that reintroduces a character limit, but applies it to each window rather than the whole transcript.

The commit will:

1. Restore a config option for the maximum number of characters per window
2. Update `render_window` to truncate windows that exceed this limit
3. Update documentation to explain the new behavior

Let me draft the commit:

```
transcript: limit window size to prevent context overflow

The windowed scoring approach splits trajectories into fixed-message windows,
but very long messages could still cause a window to exceed the model's
context window. Restore a character limit (transcript.max_window_chars)
that applies to each window: if a window exceeds this, the oldest part is
omitted to keep the most recent content.

Default is 120k characters, same as the previous transcript limit. The
monitor model (kestrel-3.1-pro) has a 128k token context window, and
characters roughly correspond to tokens in this domain.

MON-2262
```

Now for the diff:

1. Update config schema to add `max_window_chars`
2. Update `transcript.py` to use the new limit in `render_window`
3. Update documentation

Let me check if there are any other issues I missed.

Actually, while reviewing commit `ba3f0fa`, I noticed something else:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates the alert rate as `stats.alerts / self.scored`, but it should be `stats.alerts / stats.scored` to get the per-deployment alert rate.

This is a bug! The alert rate for each deployment should be based on the number of trajectories scored for that deployment, not the total number of trajectories.

Let me confirm:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, it's using `self.scored` (total trajectories) instead of `stats.scored` (trajectories for that deployment).

This would result in incorrect alert rates. For example, if one deployment has 100 trajectories with 10 alerts (10% rate) and another has 10 trajectories with 5 alerts (50% rate), but the total is 110 trajectories, the first would show 10/110 = 9.1% and the second 5/110 = 4.5%, which is wrong.

The fix is simple: change `self.scored` to `stats.scored`.

Actually, looking more carefully, `stats.scored` is the number of trajectories scored for that deployment, so the alert rate should be `stats.alerts / stats.scored`.

So the bug is in `RunSummary.finalise`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Should be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a significant bug that needs to be fixed.

Given this, I think the most critical issue to address is the incorrect alert rate calculation. The character limit issue is important too, but the alert rate bug is actively producing incorrect metrics.

Let me draft a commit for the alert rate bug:

```
metrics: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
deployment_alerts / total_scored instead of deployment_alerts / deployment_scored.
This made rates artificially low for deployments with fewer trajectories and
artificially high for deployments with more trajectories.

Fix by using the deployment's own scored count in the rate calculation.

MON-2263
```

For the diff:

1. Update `finalise` method in `RunSummary`
2. Add a test to verify the calculation

Actually, there's already a test in `test_pipeline.py` for per-deployment metrics, so I should update that test to check the alert rate.

Let me check if there are any other issues.

While I'm at it, I should also fix the character limit issue. But since the reviewer asked for a single follow-up commit, I'll focus on the most critical bug, which is the incorrect alert rate calculation.

The alert rate bug is actively producing incorrect metrics, which could lead to wrong conclusions about deployment safety. The character limit issue is a potential problem but might not be triggering in practice (if messages aren't typically long enough to exceed the context window).

So I'll propose a commit that fixes the alert rate calculation.

Wait, let me double-check. In `test_pipeline.py`:

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

This test doesn't check the alert rate, so I should add a check for that.

Actually, the test is incomplete. It should verify that the alert rate is calculated correctly.

So my follow-up commit will:
1. Fix the alert rate calculation
2. Update the test to verify it

Let me draft the commit message and diff.
