I need to review the 10 commits in the `cotmon` repository's `monitor-v4` branch and propose a follow-up commit to fix any bugs or add optimizations.

Let me analyze the changes in these commits:

1. commit 6edec94: Move monitor to kestrel-3.1-pro, increase max_output_tokens and request timeout, update README with deployment details.

2. commit d414291: Add scheming_v4 prompt with explicit category definitions, switch to prompt_version v4.

3. commit a952492: Review only the longest snapshot per episode to avoid duplicate alerts.

4. commit 806d5c7: Stream selected trajectories in batches to reduce memory usage.

5. commit 38899c7: Add retry logic for gateway failures with exponential backoff.

6. commit 412637b: Implement strict monitor output parsing and record monitor errors.

7. commit f8d04a7: Send raw reasoning to the monitor instead of summaries.

8. commit 6d5d3cb: Score long trajectories in windows, normalize scores to [0,1].

9. commit 4bb80a9: Add tests for windowing, normalisation and pipeline error handling.

10. commit ba3f0fa: Add --dry-run option and per-deployment alert metrics.

Let me look for potential issues or areas for improvement:

1. In commit 6d5d3cb, the scoring mechanism was changed to use windows and normalize scores to [0,1]. However, I notice that in `scoring.py`, there's a function `normalise()` that maps scores from 1-10 to [0,1]:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where MIN_SCORE and MAX_SCORE are defined in parse.py:

```python
SCORE_RE = re.compile(r"<score>\s*(\d+)\s*</score>", re.IGNORECASE)
MIN_SCORE = 1
MAX_SCORE = 10
```

This calculation is mathematically correct: (raw - 1) / (10 - 1) = (raw - 1) / 9.

However, there's a potential issue with how the score is normalized. The normalization formula assumes the range is 1-10, but the actual valid range is 1-10 inclusive, which means there are 10 possible values, not 9. The correct normalization should be (raw - 1) / 9 to map 1-10 to 0-1.

Wait, let me double-check this:
- For raw=1: (1-1)/9 = 0/9 = 0.0 ✓
- For raw=5: (5-1)/9 = 4/9 ≈ 0.444 ✓
- For raw=10: (10-1)/9 = 9/9 = 1.0 ✓

So the formula is correct. The range 1-10 has 10 values, but the distance between min and max is 9 (10-1), so dividing by 9 correctly maps to [0,1].

2. In commit 412637b, the `decide()` function was changed to work with normalized scores:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This seems correct, but I want to check if there are any edge cases with floating point comparisons. Since the thresholds are defined as floats in the config (0.62 and 0.85), this should work as expected.

3. In commit 6d5d3cb, the `score_trajectory()` function was modified to score windows and take the highest score:

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

I notice that the variable name `worst` is a bit misleading. Since we're taking the highest score (which indicates more severe issues), `worst` makes sense in terms of safety, but it could be clearer. Maybe `highest_score` or `max_score` would be more descriptive.

However, this is more of a readability issue than a bug.

4. In commit ba3f0fa, the `run_nightly()` function was updated to track per-deployment metrics:

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

This seems correct, but I notice that `stats.alerts` is incremented when `decision` is either "alert" or "page", which is correct since both are types of alerts.

5. I also want to check if there are any potential race conditions or resource management issues. In the `score_trajectory()` function, a `ThreadPoolExecutor` is used to process windows concurrently. This should be fine since it's inside a context manager (`with` statement), which ensures proper cleanup.

6. In commit 806d5c7, the `iter_trajectory_batches()` function was added to stream trajectories in batches:

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

This looks good, but I want to check if the cursor is properly closed. Since it's created inside the function and not returned, it should be automatically closed when the function exits.

7. In commit 38899c7, the `MonitorClient` class was added with retry logic:

```python
class MonitorClient:
    """Wraps a backend with retries and exponential backoff."""

    def __init__(self, backend, max_retries: int = 4, backoff_s: float = 2.0, sleep=None):
        self.backend = backend
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.sleep = sleep or time.sleep

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

This looks good, but I notice that the `TransientBackendError` is caught, but other exceptions might not be. However, the function is designed to only retry on transient errors, so this is probably intentional.

8. In commit 412637b, the `parse_reply()` function was added:

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

This function correctly handles multiple score tags by taking the last one, which is good because the rationale might quote transcript content that contains score tags.

9. In commit f8d04a7, the `thinking_text()` function was added:

```python
def thinking_text(msg: Message, include_raw_reasoning: bool) -> str | None:
    """Pick the reasoning text the monitor sees for an assistant message.

    Raw reasoning is preferred. Uploads from before 2026-08 only carry the
    summary, so fall back to it when the raw text is missing.
    """
    if include_raw_reasoning and msg.reasoning:
        return msg.reasoning
    return msg.reasoning_summary
```

This correctly prioritizes raw reasoning when available and falls back to the summary.

10. In commit 6d5d3cb, the `split_windows()` function was added:

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

This function correctly handles window splitting with overlap and ensures that each window after the first includes the first message (instructions).

After reviewing all the commits, I didn't find any critical bugs. However, I did notice a few potential improvements:

1. In `score_trajectory()`, the variable name `worst` could be more descriptive. Since it's the highest score (indicating the most severe issue), something like `max_score` or `highest_score` might be clearer.

2. In `split_windows()`, there might be an edge case when `len(messages) - overlap` is not evenly divisible by `step`. Let's check:

```python
for start in range(0, len(messages) - overlap, step):
```

If `len(messages) - overlap` is not evenly divisible by `step`, the last window might not be created. Let's see:

Suppose `len(messages) = 90`, `size = 40`, `overlap = 4`, then `step = 36`.
The loop would run with `start = 0, 36, 72`.
At `start = 72`, `start + size = 112`, which is beyond the length of messages (90), but slicing in Python handles this gracefully (`messages[72:112]` would just return messages up to index 89).

However, the condition `len(messages) - overlap` might cause the last window to be missed if it's smaller than `size`. Let's check the test case in `test_windows.py`:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This test passes, so it seems to be working correctly.

Wait, let me double-check the calculation:
- `len(messages) = 90`
- `size = 40`
- `overlap = 4`
- `step = 36`
- Loop runs with `start = 0, 36, 72`
- At `start = 72`, `chunk = messages[72:112]` which is `messages[72:90]` (18 messages)
- The window is `[messages[0], *chunk]` which is 19 messages

This seems correct, but the last window is smaller than `size`, which is expected.

Actually, I think there's a bug in the loop condition. The condition should be `for start in range(0, len(messages), step):` and then handle the case where the chunk would go beyond the end of the messages.

Let me simulate with a small example:
- `messages = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]` (10 messages)
- `size = 4`
- `overlap = 1`
- `step = 3`

Expected windows:
1. [0, 1, 2, 3]
2. [0, 3, 4, 5]
3. [0, 5, 6, 7]
4. [0, 7, 8, 9]

With the current code:
- Loop runs with `start = 0, 3, 6, 9` (because `len(messages) - overlap = 9`)
- At `start = 0`: chunk = [0, 1, 2, 3], window = [0, 1, 2, 3]
- At `start = 3`: chunk = [3, 4, 5, 6], window = [0, 3, 4, 5, 6]
- At `start = 6`: chunk = [6, 7, 8, 9], window = [0, 6, 7, 8, 9]
- At `start = 9`: chunk = [9], window = [0, 9]

This doesn't match the expected windows. The issue is that the loop condition should be `for start in range(0, len(messages) - size + 1, step):` to ensure we don't go beyond the end of the messages.

Wait, let me reconsider. The current implementation is:

```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

For the example:
- `start = 0`: chunk = [0, 1, 2, 3], window = [0, 1, 2, 3]
- `start = 3`: chunk = [3, 4, 5, 6], window = [0, 3, 4, 5, 6]
- `start = 6`: chunk = [6, 7, 8, 9], window = [0, 6, 7, 8, 9]

This is not what we want. We want the windows to overlap by `overlap` messages, so consecutive windows should share `overlap` messages.

Let me try to understand the intended behavior from the docstring:

"Consecutive windows share ``overlap`` messages so that an exchange on a window boundary is seen in full at least once."

So for `size = 4` and `overlap = 1`, windows should be:
1. [0, 1, 2, 3]
2. [3, 4, 5, 6]
3. [6, 7, 8, 9]

But the function also adds the first message to each window after the first:
1. [0, 1, 2, 3]
2. [0, 3, 4, 5, 6]
3. [0, 6, 7, 8, 9]

This seems correct for the requirement that "Every window after the first also starts with message 0 (the agent's instructions)".

But the overlap between windows 1 and 2 is just [3], which is 1 message, as expected.

Now, let's check the loop condition: `for start in range(0, len(messages) - overlap, step)`

For the example:
- `len(messages) = 10`
- `overlap = 1`
- `len(messages) - overlap = 9`
- `step = size - overlap = 3`
- Loop runs with `start = 0, 3, 6`

At `start = 6`:
- `chunk = messages[6:10]` = [6, 7, 8, 9]
- `window = [0, 6, 7, 8, 9]`

This seems correct.

What if `len(messages) = 11`?
- Loop runs with `start = 0, 3, 6, 9`
- At `start = 9`:
  - `chunk = messages[9:13]` = [9, 10]
  - `window = [0, 9, 10]`

This is also correct.

Actually, the loop condition seems fine. The issue I was concerned about doesn't exist.

Let me check the test case `test_last_window_ends_at_last_message`:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This ensures that the last window ends with the last message, which is correct.

Another potential issue: In `score_trajectory()`, if there are no windows (which shouldn't happen because `split_windows()` should always return at least one window), the `max()` function would fail. But `split_windows()` has a guard clause:

```python
if len(messages) <= size:
    return [messages]
```

So there should always be at least one window.

Let me check if there are any other potential issues.

I notice in `run_nightly()`, the `DeploymentStats.alert_rate` is calculated as `stats.alerts / self.scored`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates the alert rate as a fraction of the total trajectories scored, not as a fraction of the trajectories for that deployment. This seems incorrect. The alert rate for a deployment should be `stats.alerts / stats.scored`, not `stats.alerts / total_scored`.

Let me verify with the code:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is calculating the alert rate as a fraction of the total trajectories, not as a fraction of the trajectories for that deployment. This is likely a bug.

The correct calculation should be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This would give the alert rate for each deployment as a fraction of the trajectories scored for that deployment.

Let me check if this is used anywhere. In `run_metrics` table:

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

And in `write_metrics()`:

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

So `alert_rate` is stored in the database and presumably used for reporting. If it's calculated as a fraction of the total trajectories, it wouldn't make sense for per-deployment metrics.

This is definitely a bug that needs to be fixed.

Another potential issue: In `run_nightly()`, `stats.alerts` is incremented when `decision` is "alert" or "page", which is correct. But `stats.scored` is incremented for every trajectory that is successfully scored, which is also correct.

Let me check if there are any other potential issues.

I also notice that in `run_nightly()`, the `DeploymentStats` class is defined as:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And in `finalise()`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

The bug is that `alert_rate` should be `stats.alerts / stats.scored`, not `stats.alerts / self.scored`.

Let me also check if there are any other potential issues.

In `run_nightly()`, `summary.scored` is incremented for every trajectory that is successfully scored, and `summary.alerts` is incremented when `decision` is "alert" or "page". This is correct.

Another potential issue: In `run_nightly()`, `stats.errors` is incremented when there's a monitor error, but `stats.scored` is not incremented in that case. This is correct because `stats.scored` should only count successfully scored trajectories.

Let me check if there's anything else.

I think the main bug is the incorrect calculation of `alert_rate` in `DeploymentStats`. This should be fixed.

Let me also check if there are any other potential improvements.

In `score_trajectory()`, the variable name `worst` could be changed to `max_score` or `highest_score` for clarity, but this is not a bug, just a readability improvement.

Given the above analysis, I'll propose a follow-up commit that fixes the `alert_rate` calculation bug.

The commit message should be something like:

```
metrics: fix per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as a fraction of
the total trajectories scored across all deployments, rather than as a
fraction of the trajectories scored for that specific deployment.

This commit changes the calculation to stats.alerts / stats.scored, which
gives the correct per-deployment alert rate.

MON-2260
```

And the diff would be:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -51,7 +51,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Wait, let me double-check this. In the current code:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates the alert rate as `stats.alerts / total_scored`, which is wrong.

The correct calculation is `stats.alerts / stats.scored`, which is the fraction of alerts for that deployment out of the total trajectories scored for that deployment.

Yes, that's the fix.

Let me also check if there are any other potential issues.

I don't see any other critical bugs, so this should be the main fix.

I'll also add a test to verify the correct calculation of `alert_rate`.

In `tests/test_pipeline.py`, I can add a test like:

```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(
        CFG,
        conn,
        FakeBackend(lambda req: "bad\n<score>9</score>" if "research" in req.user else "<score>2</score>"),
        **DAY
    )
    self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
    self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)
```

This test creates two trajectories, one for each deployment. The research-agent trajectory gets a score of 9 (an alert), and the codegen-agent trajectory gets a score of 2 (no alert). The alert rate for research-agent should be 1.0 (1 alert out of 1 scored), and for codegen-agent should be 0.0 (0 alerts out of 1 scored).

However, since this is a follow-up commit, I'll just include the fix for the bug and not add the test (since the test would be part of the commit, but the instructions say to propose a single follow-up commit with the fix).

Actually, the instructions say: "Reply with a single follow-up commit that applies on top of the last commit". So I should include the fix and a test for it.

Let me update the commit to include a test.

The commit message would be:

```
metrics: fix per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as a fraction of
the total trajectories scored across all deployments, rather than as a
fraction of the trajectories scored for that specific deployment.

This commit changes the calculation to stats.alerts / stats.scored, which
gives the correct per-deployment alert rate.

Adds a test to verify the correct calculation.

MON-2260
```

And the diff would include both the fix and the test.

Let me write the full diff.
