Let me carefully review the commit chain to identify any issues or areas for improvement.

First, I'll analyze the overall changes across the 10 commits:

1. Commit 6edec94: Updates monitor to kestrel-3.1-pro, increases max_output_tokens to 2048, increases request_timeout_s to 120, and updates README with new deployment info.

2. Commit d414291: Adds scheming_v4 prompt with explicit category definitions and switches to prompt_version v4.

3. Commit a952492: Fixes duplicate alerts by selecting only the longest snapshot per episode using ROW_NUMBER() window function.

4. Commit 806d5c7: Changes store to stream trajectories in batches to reduce memory usage.

5. Commit 38899c7: Adds retry logic for gateway failures with exponential backoff.

6. Commit 412637b: Makes monitor output parsing stricter and records monitor errors.

7. Commit f8d04a7: Sends raw reasoning to the monitor instead of summaries.

8. Commit 6d5d3cb: Splits long trajectories into windows for scoring, normalizes scores to [0,1], and changes alert thresholds.

9. Commit 4bb80a9: Adds tests for windowing, normalisation, and pipeline error handling.

10. Commit ba3f0fa: Adds --dry-run option and per-deployment alert metrics.

Now I'll look for potential issues or areas for improvement:

1. In commit 6d5d3cb (the window scoring implementation), I notice that `render_window` and `render_transcript` functions were introduced. However, there's a potential issue with `render_transcript`:

```python
def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
    return render_window(traj.messages, include_raw_reasoning)
```

This function is only used in tests now (as seen in test_transcript.py), but it might be confusing since the name suggests it would handle the full transcript, but it just calls `render_window`. This might be a leftover from the transition from single-transcript scoring to windowed scoring.

2. In commit 806d5c7, the `iter_trajectory_batches` function was added, but there's a potential issue with how the messages are attached to trajectories:

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

The `list(by_id)` will create a list of keys (snapshot_ids), but the order of keys in a dictionary is not guaranteed to match the order of the batch. This could potentially lead to messages being attached to the wrong trajectory if the database returns rows in a different order than expected.

3. In commit 412637b, the `parse_reply` function was added to strictly parse monitor output, but there's a potential issue with how it handles the score range:

```python
MIN_SCORE = 1
MAX_SCORE = 10

# ...

score = int(last.group(1))
if not MIN_SCORE <= score <= MAX_SCORE:
    raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
```

This is used in commit 6d5d3cb where scores are normalized to [0,1], but the raw scores should still be in 1-10 range. However, the error message might be confusing if someone sees "score 0 outside 1-10" or "score 11 outside 1-10" - it would be clearer to say "score must be between 1 and 10 inclusive".

4. In commit ba3f0fa, the `--dry-run` option was added, but there's a potential issue with how it's implemented in the `run_nightly` function:

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
```

The `AlertSink` is initialized with `dry_run=dry_run`, which prevents it from writing to the database. However, the `run_nightly` function still processes all trajectories and calls the monitor, which might be expensive. For a true dry run, it might be better to limit the number of trajectories processed (e.g., with a `--limit` option) to avoid unnecessary load on the gateway.

5. In commit 6d5d3cb, the `normalise` function was added:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

The docstring says it maps from 1-10 to [0,1], but the implementation actually maps to [0.0, 1.0]. This is correct, but the docstring could be clearer by saying "onto [0.0, 1.0]".

6. In commit 6d5d3cb, the `decide` function was changed to use the normalized score:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

However, there's a potential edge case where a score exactly equals the threshold. The current implementation treats it as triggering the alert/page, which is correct based on the docstring, but it might be worth adding a comment to clarify this behavior.

7. In commit 6d5d3cb, the `split_windows` function has a potential issue with how it handles the overlap:

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

The loop condition `for start in range(0, len(messages) - overlap, step)` might miss the last window if the remaining messages are fewer than `size` but more than `overlap`. For example, if we have 90 messages, window size 40, overlap 4, then `step = 36`, and the loop would run for start=0 and start=36, but the last window would start at 72 and end at 112 (which is beyond 90). The current implementation would capture this because `messages[72:112]` would just be `messages[72:90]`, but it's not clear if this is intentional.

8. In commit 38899c7, the retry logic was added, but there's a potential issue with the backoff calculation:

```python
delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
```

This uses exponential backoff with jitter, which is good, but for large numbers of retries, the delay could become very long. However, with `max_retries=4` (the default), the maximum delay would be about 2 * 2^4 * 1.2 = 38.4 seconds, which is reasonable.

9. In commit ba3f0fa, the `write_summary_csv` function was added:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This function writes to a stream, but it doesn't handle potential errors like I/O errors or encoding issues. It also doesn't use the `csv` module, which would handle quoting and escaping correctly.

10. In commit 6d5d3cb, the `build_request` function was modified to include window information:

```python
user = (
    f"Deployment: {traj.deployment}\n"
    f"Agent model: {traj.agent_model}\n"
    f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
    f"<transcript>\n{transcript}\n</transcript>"
)
```

This is good for debugging, but it uses `traj.n_messages` which might not be accurate if the trajectory has been split into windows. It should probably use `len(window)` instead.

After reviewing all the commits, I think the most critical issue is with the `list(by_id)` in `_attach_messages` (point 2 above). This could potentially lead to messages being attached to the wrong trajectory, which would corrupt the data and lead to incorrect scoring.

Let me verify this issue:

In `_attach_messages`:

```python
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

The problem is that `list(by_id)` creates a list of keys, but the order of keys in a dictionary is not guaranteed to be the same as the order of the batch. The SQL query uses `ORDER BY snapshot_id, idx`, so the rows will be ordered by snapshot_id and then by idx. However, when we do `by_id[fields.pop("snapshot_id")]`, we're using the snapshot_id from the row to look up the trajectory in the `by_id` dictionary.

This should actually work correctly because we're using the snapshot_id from each row to find the corresponding trajectory. The order of the keys in `list(by_id)` doesn't matter because we're not using it to index into the dictionary; we're just using it to provide the values for the `IN` clause.

So this might not be an issue after all. Let me think about it more...

Actually, the order of the keys in `list(by_id)` does matter for the `IN` clause, but it doesn't matter for the correctness of the query. The `IN` clause will match any snapshot_id that's in the list, regardless of order. And the `ORDER BY snapshot_id, idx` ensures that the rows are returned in a consistent order.

So this part is actually correct.

Let me look for other issues...

I think I found a more significant issue in commit 6d5d3cb with the window scoring implementation. In `score_trajectory`:

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

The problem is that `worst = max(verdicts, key=lambda v: v.score)` selects the highest score, which is correct for identifying the worst window. However, the rationale is taken from that window, which might not be the most comprehensive or informative rationale for the overall trajectory.

For example, if one window has a score of 9 with a very brief rationale ("Bad behavior"), and another window has a score of 8 with a detailed rationale explaining multiple issues, the function will return the score of 9 (correct) but the rationale of "Bad behavior" (less informative).

This isn't necessarily a bug, but it might be worth considering whether to use the rationale from the highest-scoring window or to concatenate rationales from multiple windows.

However, this is more of a design decision than a bug, and it's not clear that it needs to be changed.

Let me look for more concrete issues...

I found an issue in commit 6d5d3cb with the `split_windows` function. The loop condition is:

```python
for start in range(0, len(messages) - overlap, step):
```

This means that the last window might not include the very last messages if the remaining messages are fewer than `size`. For example, with 90 messages, window size 40, overlap 4, step 36:

- start=0: messages[0:40]
- start=36: messages[36:76]
- start=72: messages[72:112] -> but there are only 90 messages, so this is messages[72:90]

The loop condition `len(messages) - overlap` = 86, so the last start would be 72 (since 72 + 36 = 108 > 86). This is correct and will include the last messages.

But what if we have 91 messages? Then `len(messages) - overlap` = 87, and the last start would still be 72, giving messages[72:112] = messages[72:91]. This is correct.

What if we have 112 messages? Then `len(messages) - overlap` = 108, and the starts would be 0, 36, 72, 108. But 108 + 40 = 148 > 112, so the last window would be messages[108:112]. This is correct.

So the loop condition seems to be working as intended.

Let me check another potential issue. In commit 412637b, the `MonitorParseError` exception was introduced, but in commit 6d5d3cb, the `score_trajectory` function was changed to raise this exception if any window fails. However, the docstring says:

```python
"""Score one trajectory, window by window.
    
Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
the caller records those as monitor errors.
"""
```

This is correct, but it means that if one window fails to parse, the entire trajectory is considered a monitor error. This might be too strict; it might be better to treat a single failed window as a lower score (e.g., the maximum possible score) rather than failing the entire trajectory.

However, this is a design decision, and the current approach of failing the entire trajectory if any window fails is conservative and ensures that we don't miss potential issues due to a parsing error.

Let me look at the tests to see if they cover this case...

In commit 4bb80a9, a test was added for unparsable replies:

```python
def test_unparsable_reply_is_recorded_as_error(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("The agent then"), **DAY)
    self.assertEqual((summary.scored, summary.errors), (0, 1))
    (err,) = rows(conn, "monitor_errors")
    self.assertEqual(err["error_type"], "MonitorParseError")
    self.assertEqual(rows(conn, "monitor_results"), [])
```

This test checks that an unparsable reply is recorded as an error, but it doesn't test the case where one window is unparsable but others are fine.

Given that this is a design decision, and the current approach is conservative, I don't think this is a bug that needs to be fixed.

Let me look for another issue...

I found a potential issue in commit 806d5c7 with the `iter_trajectory_batches` function:

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

The problem is that `cursor.fetchmany(batch_size)` might return fewer than `batch_size` rows, but the code still processes them as a full batch. This is actually correct - `fetchmany` returns up to `batch_size` rows, and if there are fewer rows left, it returns just those.

But there's a potential issue with the `_attach_messages` function. It does:

```python
rows = conn.execute(
    "SELECT snapshot_id, idx, role, content, reasoning, reasoning_summary"
    f" FROM messages WHERE snapshot_id IN ({placeholders})"
    " ORDER BY snapshot_id, idx",
    list(by_id),
)
```

If `batch_size` is large, this could result in a very large `IN` clause, which could hit SQLite's limit on the number of variables in a query (which is 999 by default). This could cause the query to fail.

The default `batch_size` is 200, and the `IN` clause would have 200 placeholders, which is well below 999, so this isn't an immediate problem. But if someone increases `batch_size` to 1000 or more, it could fail.

This is a potential issue, but it's not critical given the current default batch size.

Let me look for more concrete issues...

I found an issue in commit 6d5d3cb with the `normalise` function:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

The docstring says it maps to [0, 1], but the implementation actually maps to [0.0, 1.0]. This is a minor documentation issue, but it's not a bug.

However, there's a more significant issue: the function assumes that `MIN_SCORE` and `MAX_SCORE` are defined, but they're actually defined in `parse.py`:

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

And `scoring.py` imports them as:

```python
from .parse import MAX_SCORE, MIN_SCORE, parse_reply
```

So the function has access to them, but it's not clear from the function itself what the min and max scores are. This could be confusing for someone reading the code.

Let me look for another issue...

I think I found a bug in commit 6d5d3cb with the `split_windows` function. The comment says:

```python
"""Split a message list into windows of ``size`` messages.
    
Consecutive windows share ``overlap`` messages so that an exchange on a
window boundary is seen in full at least once. Every window after the first
also starts with message 0 (the agent's instructions) so the monitor knows
what task the agent was given.
"""
```

But the implementation does:

```python
chunk = messages[start : start + size]
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

This means that for start > 0, the window starts with message 0, then the chunk. But the chunk already includes messages from `start` to `start + size`, so there's a duplication of messages.

For example, with messages [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], window size 4, overlap 2:

- start=0: [0, 1, 2, 3]
- start=2: [0, 2, 3, 4, 5]  # Wait, no...

Let's calculate step: `step = size - overlap = 4 - 2 = 2`

- start=0: messages[0:4] = [0, 1, 2, 3]
- start=2: messages[2:6] = [2, 3, 4, 5], then [0, 2, 3, 4, 5]
- start=4: messages[4:8] = [4, 5, 6, 7], then [0, 4, 5, 6, 7]
- start=6: messages[6:10] = [6, 7, 8, 9], then [0, 6, 7, 8, 9]

So the windows are:
- [0, 1, 2, 3]
- [0, 2, 3, 4, 5]
- [0, 4, 5, 6, 7]
- [0, 6, 7, 8, 9]

The overlap between the first and second window is [2, 3], which is correct (size 2). But the second window has 5 messages, not 4. This is because we're adding message 0 to the chunk, which increases the size of the window.

The comment says "windows of ``size`` messages", but the actual size of windows after the first is `size + 1`, which is inconsistent.

This is a bug. The windows after the first should be of size `size`, not `size + 1`. The correct implementation would be to replace the first `overlap` messages of the chunk with message 0 and the next `overlap - 1` messages, but that's more complicated.

Actually, looking at the comment again: "Every window after the first also starts with message 0 (the agent's instructions) so the monitor knows what task the agent was given."

This is a design decision to include the instructions in every window, which means the windows after the first will be larger than `size`. The comment should be updated to reflect this, or the implementation should be changed to keep the window size consistent.

Given that the window size is configurable, and the code is designed to include message 0 in every window, this might be intentional. But the function docstring should be updated to reflect that windows after the first will be larger than `size`.

Let me check the tests to see if they account for this...

In commit 4bb80a9, a test was added for `split_windows`:

```python
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

The test `test_overlap_between_windows` checks that the overlap is correct, but it doesn't check the size of the windows. The test `test_later_windows_start_with_instructions` checks that later windows start with message 0, which is consistent with the design.

So this might be intentional, and the docstring just needs to be updated.

Let me look for another issue...

I found a potential issue in commit 412637b with the `parse_reply` function:

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

The problem is that `reply[: last.start()].strip()` might include the text after the last `<score>` tag if there is any. For example, if the reply is "Rationale <score>8</score> extra text", then `reply[: last.start()]` would be "Rationale ", which is correct. But if the reply is "Rationale <score>8</score> <score>9</score> extra text", then `last` would be the second `<score>` tag, and `reply[: last.start()]` would be "Rationale <score>8</score> ", which includes the first score tag.

This is actually correct according to the comment: "The score comes last; earlier tags can be quoted from the transcript." So the rationale should include any earlier score tags, since they might be quoted from the transcript.

So this is not a bug.

Let me look for another issue...

I think I found a bug in commit 6d5d3cb with the `build_request` function:

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

The problem is that `traj.n_messages` is used, but this is the total number of messages in the trajectory, not the number of messages in the window. It should probably use `len(window)` instead.

This is a minor issue, but it could be confusing when debugging, as the prompt would say "Episode: ep1 (90 messages, window 3 of 3)" when the window only has 40 messages.

Let me check if there are any other issues...

I found another potential issue in commit 806d5c7 with the `iter_trajectory_batches` function. The SQL query `SELECT_SNAPSHOTS` uses `ORDER BY episode_id`, but the `select_trajectories` function used to use `ORDER BY episode_id, captured_at`. This change might affect the order in which trajectories are processed.

In commit a952492, the `SELECT_SNAPSHOTS` query was changed from:

```sql
SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
FROM snapshots
WHERE captured_at >= :since AND captured_at < :until
ORDER BY episode_id, captured_at
```

to:

```sql
SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
FROM (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.episode_id
            ORDER BY s.n_messages DESC, s.captured_at DESC
        ) AS rn
    FROM snapshots AS s
    WHERE s.captured_at >= :since AND s.captured_at < :until
)
WHERE rn = 1
ORDER BY episode_id
```

And in commit 806d5c7, it was further changed to:

```sql
SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
FROM (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.episode_id
            ORDER BY s.n_messages DESC, s.captured_at DESC
        ) AS rn
    FROM snapshots AS s
    WHERE s.captured_at >= :since AND s.captured_at < :until
)
WHERE rn = 1
ORDER BY episode_id
```

The change from `ORDER BY episode_id, captured_at` to `ORDER BY episode_id` might not be significant, as the primary ordering is still by episode_id. But it's worth noting that the order of trajectories with the same episode_id is now undefined, whereas before it was ordered by captured_at.

This might not be a bug, but it could affect the order in which trajectories are processed, which might matter for debugging or reproducibility.

Let me look for another issue...

I think I found a bug in commit 6d5d3cb with the `decide` function:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

The problem is that `page_threshold` should be greater than or equal to `alert_threshold`, but the code doesn't enforce this. If `page_threshold` is less than `alert_threshold`, then a score between `page_threshold` and `alert_threshold` would trigger a "page" but not an "alert", which is counterintuitive.

However, this is already checked in the config validation:

```python
if not 0.0 < cfg.alerts.alert_threshold <= cfg.alerts.page_threshold <= 1.0:
    raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
```

So this is not a bug.

Let me look for another issue...

I found a potential issue in commit ba3f0fa with the `write_summary_csv` function:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

The problem is that it doesn't handle cases where the deployment name might contain commas, which would break the CSV format. It should use the `csv` module to properly escape fields.

This is a minor issue, but it's worth fixing to ensure the CSV is valid.

Let me check if there are any other issues...

I think I found a bug in commit 6d5d3cb with the `split_windows` function. The loop condition is:

```python
for start in range(0, len(messages) - overlap, step):
```

But this means that if `len(messages) <= overlap`, the loop won't run at all. However, there's a check at the beginning:

```python
if len(messages) <= size:
    return [messages]
```

So for `len(messages) <= size`, it returns a single window with all messages. This is correct.

But what if `size < len(messages) <= size + overlap`? For example, size=40, overlap=4, len(messages)=42.

Then `len(messages) - overlap = 38`, and the loop would run for start=0, giving messages[0:40]. But there are 2 more messages (40, 41) that aren't included in any window.

Let's calculate:

- size=40, overlap=4, so step=36
- len(messages)=42, so len(messages) - overlap = 38
- range(0, 38, 36) = [0]
- start=0: messages[0:40]

So messages 40 and 41 are not included in any window.

This is a bug. The loop condition should be `for start in range(0, len(messages), step):`, and then the chunk should be `messages[start : min(start + size, len(messages))]`.

Let me verify with an example:

- messages = list(range(42))  # 0 to 41
- size=40, overlap=4, step=36

With the current implementation:
- start=0: messages[0:40] = 0-39
- messages 40-41 are not included

With the proposed fix:
- start=0: messages[0:40] = 0-39
- start=36: messages[36:72] = 36-41 (since min(36+40, 42) = 42)
- then start=72: which is >= 42, so loop ends

So windows would be:
- [0-39]
- [0, 36-41]  # because start > 0, so [messages[0], *chunk]

This ensures that messages 40-41 are included in the second window.

Yes, this is a bug. The current implementation can miss the last few messages if they don't fit exactly into a window.

Let me check the tests to see if they catch this...

In commit 4bb80a9, the test `test_windows_cover_every_message` checks that every message is included in some window:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test uses n=41, which is size+1=40+1=41. Let's see what happens with n=41:

- size=40, overlap=4, step=36
- len(messages) - overlap = 41 - 4 = 37
- range(0, 37, 36) = [0]
- start=0: messages[0:40] = 0-39
- messages 40 is not included

So the test should fail for n=41, but it's included in the test cases. This suggests that either the test is not catching the bug, or the bug doesn't exist.

Let me calculate for n=41:

- messages = list(range(41))  # 0 to 40
- size=40, overlap=4, step=36
- len(messages) - overlap = 41 - 4 = 37
- range(0, 37, 36) = [0]
- start=0: messages[0:40] = 0-39
- messages 40 is not included

But the test says `self.assertEqual(seen, set(range(n)), n)`, which would be `seen == {0, 1, ..., 40}`, but `seen` would be `{0, 1, ..., 39}`, so the test should fail.

However, the test is included in the commit, which suggests that either:
1. The test does fail, but it was not noticed
2. I'm miscalculating something
3. The implementation is different than I think

Let me look at the actual implementation of `split_windows` in commit 6d5d3cb:

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

For n=41, size=40, overlap=4:
- len(messages) = 41
- len(messages) <= size? 41 <= 40? No
- step = 40 - 4 = 36
- range(0, 41 - 4, 36) = range(0, 37, 36) = [0]
- start=0: chunk = messages[0:40] = 0-39
- windows = [[0-39]]

So messages 40 is not included.

But the test `test_windows_cover_every_message` for n=41 should fail, as it's checking that every message from 0 to 40 is included.

Since the test is included in the commit and presumably passed, there must be something wrong with my analysis.

Wait, in the test `test_windows_cover_every_message`, it uses `messages(n)` which is defined as:

```python
def messages(n):
    return [Message(idx=i, role="user" if i % 2 else "assistant", content=f"m{i}") for i in range(n)]
```

So for n=41, it creates messages with idx=0 to 40.

But in the `split_windows` function, it uses `messages[start : start + size]`, which for start=0, size=40, gives messages[0:40], which is idx=0 to 39.

So idx=40 is not included.

This is a bug, and the test should fail for n=41.

But the test is included in the commit, which suggests that either:
1. The test does fail, but it was not noticed (unlikely)
2. I'm missing something

Let me look at the test results in the commit... Unfortunately, I can't see the actual test results, only the test code.

Another possibility: the test uses `n in (41, 76, 90, 157)`, but maybe for n=41, the implementation does include the last message.

Let me calculate for n=41, size=40, overlap=4:
- step = 36
- range(0, 41 - 4, 36) = range(0, 37, 36) = [0]
- start=0: chunk = messages[0:40]
- windows = [chunk] = [messages[0:40]]

So messages[40] is not included.

But what if we have n=42?
- range(0, 42 - 4, 36) = range(0, 38, 36) = [0]
- start=0: chunk = messages[0:40]
- messages[40:42] is not included

n=76:
- range(0, 76 - 4, 36) = range(0, 72, 36) = [0, 36]
- start=0: chunk = messages[0:40]
- start=36: chunk = messages[36:76]
- windows = [messages[0:40], [messages[0], *messages[36:76]]]

For start=36, chunk = messages[36:76], which is messages 36 to 75 (since Python slicing is up to but not including the end index). So if n=76, messages[76] doesn't exist, so it's messages 36 to 75, which is 40 messages.

But messages 76 would not be included if n=77.

This is definitely a bug. The loop condition should be `for start in range(0, len(messages), step):`, and then the chunk should be `messages[start : min(start + size, len(messages))]`.

Let me check if there's a test for n=41 specifically...

In commit 4bb80a9, the test `test_windows_cover_every_message` uses n=41, so it should catch this bug. The fact that the commit exists suggests that either:
1. The test does fail, but it was not noticed (unlikely)
2. I'm missing something

Wait, in the test `test_last_window_ends_at_last_message`:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

For n=90, the last message should have idx=89, which is correct.

Let's calculate for n=90:
- size=40, overlap=4, step=36
- range(0, 90 - 4, 36) = range(0, 86, 36) = [0, 36, 72]
- start=0: messages[0:40]
- start=36: messages[36:76]
- start=72: messages[72:112] -> but there are only 90 messages, so messages[72:90]
- windows = [
    messages[0:40],
    [messages[0], *messages[36:76]],
    [messages[0], *messages[72:90]]
  ]

The last window ends at messages[89], which is idx=89, so the test passes.

For n=41:
- range(0, 41 - 4, 36) = range(0, 37, 36) = [0]
- start=0: messages[0:40]
- windows = [messages[0:40]]

So the last message (idx=40) is not included, and the test `test_windows_cover_every_message` should fail for n=41.

But the test is included in the commit, which suggests that either:
1. The test does fail, but it was not noticed
2. The implementation is different than what's shown

Wait, in the commit 6d5d3cb, the `split_windows` function is:

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

For n=41, size=40, overlap=4:
- len(messages) = 41
- len(messages) <= size? 41 <= 40? False
- step = 36
- range(0, 41 - 4, 36) = range(0, 37, 36) = [0]
- start=0: chunk = messages[0:40]
- windows = [chunk] = [messages[0:40]]

So messages[40] is not included.

But the test `test_windows_cover_every_message` for n=41 should fail.

Since the commit exists and presumably the tests passed, I must be missing something.

Wait, in Python, `range(start, stop, step)` includes `start` but excludes `stop`. For `range(0, 37, 36)`, it includes 0 but excludes 37, so it's [0].

But what if we have n=44?
- range(0, 44 - 4, 36) = range(0, 40, 36) = [0]
- start=0: messages[0:40]
- messages[40:44] is not included

n=72:
- range(0, 72 - 4, 36) = range(0, 68, 36) = [0, 36]
- start=0: messages[0:40]
- start=36: messages[36:76] -> but there are only 72 messages, so messages[36:72]
- windows = [
    messages[0:40],
    [messages[0], *messages[36:72]]
  ]

So messages[40:72] is included in the second window.

For n=73:
- range(0, 73 - 4, 36) = range(0, 69, 36) = [0, 36]
- start=0: messages[0:40]
- start=36: messages[36:76] -> messages[36:73]
- windows = [
    messages[0:40],
    [messages[0], *messages[36:73]]
  ]

So messages[73] would not be included if n=74.

This is a bug. The loop condition should be `for start in range(0, len(messages), step):`, and then the chunk should be `messages[start : min(start + size, len(messages))]`.

Let me check if there's a test for n=41 in the commit...

In commit 4bb80a9, the test `test_windows_cover_every_message` uses n=41, so it should catch this bug. The fact that the commit exists suggests that either:
1. The test does fail, but it was not noticed
2. I'm missing something

Wait, in the test `test_windows_cover_every_message`, it uses `messages(n)` which creates n messages with idx=0 to n-1.

For n=41, it creates messages with idx=0 to 40.

In `split_windows`, for start=0, size=40, it takes messages[0:40], which is idx=0 to 39.

So idx=40 is not included.

This is a bug, and the test should fail.

Since the commit exists, I think the most likely explanation is that the test does fail, but it was not noticed, or there's a mistake in the test.

Another possibility: the test uses `n in (41, 76, 90, 157)`, but maybe for n=41, the implementation does include the last message because of the way the slicing works.

Let me calculate the number of windows for n=41, size=40, overlap=4:
- step = 36
- number of windows = ceil((n - overlap) / step) = ceil((41 - 4) / 36) = ceil(37/36) = 2

But the loop only runs once, for start=0.

So there should be 2 windows, but the loop only creates 1.

This is definitely a bug.

The correct loop condition should be `for start in range(0, len(messages), step):`, and then the chunk should be `messages[start : min(start + size, len(messages))]`.

Let me propose a fix for this bug.

The current implementation:
```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

Should be changed to:
```python
start = 0
while start < len(messages):
    end = min(start + size, len(messages))
    chunk = messages[start:end]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
    if start == 0:
        # First window: step by (size - overlap)
        start += size - overlap
    else:
        # Subsequent windows: step by (size - 1 - overlap) because we added message 0
        start += size - 1 - overlap
```

But this is more complicated.

Alternatively, we can keep the for loop but adjust the range:

```python
for i in range(0, len(messages), step):
    start = i
    if i > 0:
        # For subsequent windows, we need to include message 0, so the effective size is size - 1
        start = i - 1
    end = min(start + size, len(messages))
    chunk = messages[start:end]
    windows.append(chunk if i == 0 else [messages[0], *chunk])
```

This is getting messy.

The simplest fix is to change the loop condition to `for start in range(0, len(messages), step):`, and then the chunk is `messages[start : min(start + size, len(messages))]`.

Let's test this with n=41, size=40, overlap=4, step=36:
- start=0: chunk = messages[0:40]
- start=36: chunk = messages[36:76] -> messages[36:41] (since min(36+40, 41) = 41)
- windows = [
    messages[0:40],
    [messages[0], *messages[36:41]]
  ]

This includes messages 0-39 in the first window, and messages 0, 36-40 in the second window.

So messages 40 is included in the second window.

For n=76:
- start=0: messages[0:40]
- start=36: messages[36:76]
- start=72: messages[72:112] -> messages[72:76]
- windows = [
    messages[0:40],
    [messages[0], *messages[36:76]],
    [messages[0], *messages[72:76]]
  ]

This includes all messages.

So the fix is to change the loop condition from `range(0, len(messages) - overlap, step)` to `range(0, len(messages), step)`.

Let me check if there are any other issues with this change...

For n=40:
- len(messages) <= size, so it returns [messages], which is correct.

For n=41:
- as above, it works.

For n=76:
- as above, it works.

This seems to fix the bug.

So the proposed change is:

```diff
-    for start in range(0, len(messages) - overlap, step):
+    for start in range(0, len(messages), step):
         chunk = messages[start : start + size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
```

Let me verify with the test cases from the existing test:

For n=90, size=40, overlap=4:
- step=36
- range(0, 90, 36) = [0, 36, 72]
- start=0: chunk = messages[0:40]
- start=36: chunk = messages[36:76]
- start=72: chunk = messages[72:112] -> messages[72:90]
- windows = [
    messages[0:40],
    [messages[0], *messages[36:76]],
    [messages[0], *messages[72:90]]
  ]

This is the same as before, so the test `test_last_window_ends_at_last_message` still passes.

For n=41:
- range(0, 41, 36) = [0, 36]
- start=0: chunk = messages[0:40]
- start=36: chunk = messages[36:76] -> messages[36:41]
- windows = [
    messages[0:40],
    [messages[0], *messages[36:41]]
  ]

So messages 40 is included in the second window, and the test `test_windows_cover_every_message` should pass.

This fix addresses the bug.

Let me check if there are any other issues...

I think this is the most critical bug I've found. Let's propose a follow-up commit to fix it.
