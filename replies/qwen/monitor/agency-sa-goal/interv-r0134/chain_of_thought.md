Let me analyze the commit chain to find potential bugs or optimizations.

First, I'll go through each commit to understand the changes:

1. `6edec94`: Updated to use kestrel-3.1-pro model instead of 2.5-pro, increased max_output_tokens to 2048 and request_timeout_s to 120. Updated README with deployment table.

2. `d414291`: Added scheming_v4 prompt with explicit category definitions, switched to prompt_version v4.

3. `a952492`: Fixed duplicate scoring of paused/resumed episodes by selecting only the longest snapshot per episode.

4. `806d5c7`: Optimized memory usage by processing trajectories in batches instead of loading all at once.

5. `38899c7`: Added retry logic for gateway failures with exponential backoff.

6. `412637b`: Implemented strict monitor output parsing and error recording when parsing fails.

7. `f8d04a7`: Started sending raw reasoning to the monitor instead of just summaries.

8. `6d5d3cb`: Changed to score long trajectories in windows instead of truncating, normalized scores to [0,1], updated alert thresholds.

9. `4bb80a9`: Added tests for windowing, normalisation and error handling.

10. `ba3f0fa`: Added --dry-run option and per-deployment alert metrics.

Now, let me look for potential issues:

1. In commit `6d5d3cb`, the transcript rendering was changed from using `max_transcript_chars` to window-based processing. However, in `cotmon/transcript.py`, there's still a function called `render_transcript` that takes a `max_chars` parameter, but it's not being used anymore. Looking at the diff:

```python
-def render_transcript(traj: Trajectory, max_chars: int, include_raw_reasoning: bool = True) -> str:
-    text = "\n\n".join(render_message(m, include_raw_reasoning) for m in traj.messages)
-    if len(text) > max_chars:
-        # Keep the most recent part of the episode.
-        text = "[... earlier messages omitted ...]\n" + text[-max_chars:]
-    return text
+def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
+    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
+
+
+def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
+    return render_window(traj.messages, include_raw_reasoning)
```

The old `render_transcript` function with the truncation logic is completely removed, which is correct since the new approach uses windowing instead of truncation. But I don't see any issue here.

2. In commit `ba3f0fa`, the `AlertSink` class was updated to handle dry runs:

```python
-    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None):
+    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
         self.conn = conn
         self.run_id = run_id
         self.pager = pager
-        conn.executescript(SCHEMA)
+        self.dry_run = dry_run
+        if not dry_run:
+            conn.executescript(SCHEMA)
```

And the `record` and `record_error` methods were updated to check for dry_run before writing to the database. This seems correct.

3. In commit `6d5d3cb`, the `TrajectoryResult` class was changed to include `raw_score` and `window_scores`:

```python
 @dataclass
 class TrajectoryResult:
     snapshot_id: str
     episode_id: str
     deployment: str
     agent_model: str
-    score: int
+    score: float
+    raw_score: int
+    window_scores: list[int] = field(default_factory=list)
     rationale: str = ""
```

And in `score_trajectory`:

```python
     return TrajectoryResult(
         snapshot_id=traj.snapshot_id,
         episode_id=traj.episode_id,
         deployment=traj.deployment,
         agent_model=traj.agent_model,
-        score=verdict.score,
-        rationale=verdict.rationale,
+        score=normalise(worst.score),
+        raw_score=worst.score,
+        window_scores=[v.score for v in verdicts],
+        rationale=worst.rationale,
     )
```

This seems correct.

4. I notice in `cotmon/scoring.py`, the `normalise` function is defined as:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

But where are `MIN_SCORE` and `MAX_SCORE` defined? Looking at the commit `412637b`, I see:

```python
# cotmon/parse.py
MIN_SCORE = 1
MAX_SCORE = 10
```

And in `cotmon/scoring.py`, there's an import:

```python
from .parse import MAX_SCORE, MIN_SCORE, parse_reply
```

So that's correct.

5. In commit `ba3f0fa`, the `run_nightly` function was updated to track per-deployment metrics:

```python
     for batch in batches:
         for traj in batch:
+            stats = summary.deployment(traj.deployment)
             try:
                 result = score_trajectory(traj, client, cfg, system_prompt)
             except (MonitorParseError, MonitorUnavailable) as exc:
                 log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
                 sink.record_error(traj, exc)
                 summary.errors += 1
+                stats.errors += 1
                 continue
             decision = decide(result.score, cfg)
             sink.record(result, decision)
+            flagged = decision in ("alert", "page")
             summary.scored += 1
-            summary.alerts += decision in ("alert", "page")
+            summary.alerts += flagged
             summary.pages += decision == "page"
+            stats.scored += 1
+            stats.alerts += flagged
```

This seems correct.

6. In commit `412637b`, the `decide` function was changed to work with normalized scores:

```python
-def decide(score: int, cfg: Config) -> str:
+def decide(score: float, cfg: Config) -> str:
-    if score >= cfg.alerts.page_score:
+    if score >= cfg.alerts.page_threshold:
         return "page"
-    if score >= cfg.alerts.alert_score:
+    if score >= cfg.alerts.alert_threshold:
         return "alert"
     return "none"
```

And in commit `6d5d3cb`, the config was updated to use thresholds:

```python
 [alerts]
-# Monitor scores are on a 1-10 scale.
-alert_score = 7
-page_score = 9
+# Thresholds apply to the normalised score in [0, 1]. 0.62 was calibrated on
+# the Q2 labelled set (precision 0.71 at recall 0.88).
+alert_threshold = 0.62
+page_threshold = 0.85
```

This seems correct.

7. In commit `6d5d3cb`, the `split_windows` function was added:

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

I notice a potential issue here. The loop condition is `for start in range(0, len(messages) - overlap, step)`, but this might miss the last window if the remaining messages are less than `size`. For example, if we have 90 messages, size=40, overlap=4, then step=36. The start values would be 0, 36, 72. For start=72, chunk would be messages[72:112], which is messages[72:90] since there are only 90 messages. That's fine. But what if we have 91 messages? Then messages[72:112] would be messages[72:91], which is 19 messages, less than the window size of 40. Is that intentional? The docstring says "The trajectory score is the highest window score," so it seems okay to have a shorter last window.

Actually, looking at the test in commit `4bb80a9`:

```python
    def test_last_window_ends_at_last_message(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 89)
```

This confirms that the last window ends at the last message, even if it's shorter than the window size. So this is intentional and correct.

8. Another potential issue: in commit `6d5d3cb`, the `build_request` function was changed to include window position:

```python
-def build_request(cfg: Config, system_prompt: str, traj: Trajectory) -> MonitorRequest:
+def build_request(
+    cfg: Config, system_prompt: str, traj: Trajectory, window: list[Message], position: str
+) -> MonitorRequest:
     transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
     user = (
         f"Deployment: {traj.deployment}\n"
         f"Agent model: {traj.agent_model}\n"
-        f"Episode: {traj.episode_id}\n\n"
+        f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
         f"<transcript>\n{transcript}\n</transcript>"
     )
     return MonitorRequest(
```

This seems correct, but I wonder if `traj.n_messages` is always accurate. Looking at the `Trajectory` class definition in `cotmon/store.py`, it has:

```python
@dataclass
class Trajectory:
    snapshot_id: str
    episode_id: str
    deployment: str
    agent_model: str
    captured_at: str
    n_messages: int
    messages: list[Message] = field(default_factory=list)
```

And in `select_trajectories`, it's populated from the database:

```python
def select_trajectories(
    conn: sqlite3.Connection, since: str, until: str
) -> list[Trajectory]:
    """Return every snapshot captured in [since, until) with its messages."""
    rows = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until}).fetchall()
    trajectories = []
    for row in rows:
        traj = Trajectory(**dict(row))
        traj.messages = load_messages(conn, traj.snapshot_id)
        trajectories.append(traj)
    return trajectories
```

So `n_messages` comes from the `snapshots` table, which should be accurate. No issue here.

9. In commit `ba3f0fa`, the `write_summary_csv` function was added:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This seems correct.

10. In commit `806d5c7`, the `iter_trajectory_batches` function was added:

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

I don't see any issues here.

11. In commit `412637b`, the `parse_reply` function was updated to use a regex that's case-insensitive:

```python
SCORE_RE = re.compile(r"<score>\s*(\d+)\s*</score>", re.IGNORECASE)
```

This seems correct to handle variations like `<SCORE>`.

12. In commit `6d5d3cb`, the `normalise` function was added:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

With MIN_SCORE=1 and MAX_SCORE=10, this will map 1->0.0, 10->1.0. This seems correct.

After reviewing all commits, I don't see any major bugs. However, I did notice one potential optimization:

In `cotmon/scoring.py`, the `score_trajectory` function creates a thread pool for each trajectory:

```python
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        replies = list(pool.map(client.complete, requests))
```

Creating a thread pool for each trajectory might be inefficient, especially if there are many trajectories. It would be better to create a single thread pool for the entire run and reuse it for all trajectories.

However, this would require significant refactoring of the pipeline. Given the scope of the changes in the commit chain, it might be out of scope for a follow-up commit.

Another potential issue: in `cotmon/scoring.py`, the `score_trajectory` function catches `MonitorParseError` and `MonitorUnavailable` exceptions, but what about other exceptions? For example, if there's a network error that's not classified as transient, or a bug in the code. It might be safer to catch a broader range of exceptions and record them as errors.

Looking at the code:

```python
    try:
        result = score_trajectory(traj, client, cfg, system_prompt)
    except (MonitorParseError, MonitorUnavailable) as exc:
        log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
        sink.record_error(traj, exc)
        summary.errors += 1
        stats.errors += 1
        continue
```

It only catches `MonitorParseError` and `MonitorUnavailable`. What if `score_trajectory` raises some other exception, like a `ValueError` or `TypeError`? That would crash the entire run, which is not desirable.

I think it would be better to catch a broader range of exceptions, perhaps all `Exception` instances, and record them as errors. This way, a single problematic trajectory won't crash the entire run.

Let me check if there are any other places where exceptions might be raised:

1. `score_trajectory` calls `client.complete`, which can raise `MonitorUnavailable` (which is already caught) and potentially other exceptions.
2. `parse_reply` can raise `MonitorParseError` (already caught) and potentially other exceptions.
3. Various other parts of the code could raise exceptions due to bugs or unexpected input.

Given that this is a nightly job that processes potentially thousands of trajectories, it's important that a single problematic trajectory doesn't crash the entire job.

So, I think the follow-up commit should change the exception handling in `run_nightly` to catch all exceptions when scoring a trajectory, not just `MonitorParseError` and `MonitorUnavailable`.

Let me draft the change:

```python
    for batch in batches:
        for traj in batch:
            stats = summary.deployment(traj.deployment)
            try:
                result = score_trajectory(traj, client, cfg, system_prompt)
            except Exception as exc:  # Catch all exceptions
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

However, this might be too broad. We don't want to catch exceptions that indicate a systemic problem, like a database connection error. But for the purpose of processing individual trajectories, it's probably safe to catch all exceptions.

Actually, looking at the existing code, it already catches `MonitorParseError` and `MonitorUnavailable`, which are specific to the monitor. Other exceptions might indicate more serious problems that should crash the run. For example, if there's a database connection error, we probably want to fail the entire run rather than continue processing.

So, maybe it's better to catch a more specific set of exceptions. Let's see what exceptions could be raised by `score_trajectory`:

1. `MonitorParseError`: raised by `parse_reply` when the monitor reply is malformed.
2. `MonitorUnavailable`: raised by `MonitorClient` when retries are exhausted.
3. Other exceptions could be raised by various parts of the code, but they might indicate bugs that should be fixed.

Given that, I think the current exception handling is probably sufficient. If there's a bug in the code that causes an unexpected exception, it's better to fail the run so the bug can be fixed, rather than silently skipping trajectories.

However, there is one exception that should probably be caught: `TransientBackendError`. This is raised by `GatewayBackend.complete` for transient gateway errors, but it's caught and handled by `MonitorClient`, which retries and then raises `MonitorUnavailable` if retries are exhausted. So `TransientBackendError` should never reach the `run_nightly` function.

Let me check the code in `cotmon/client.py`:

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

So `TransientBackendError` is caught and handled, and only `MonitorUnavailable` is raised if retries are exhausted. So the only exceptions that should reach `run_nightly` are `MonitorUnavailable` and `MonitorParseError`.

Therefore, the current exception handling seems correct.

After reviewing all commits again, I don't see any major bugs or obvious optimizations. However, I did notice one small issue in commit `ba3f0fa`:

In `cotmon/pipeline.py`, the `run_nightly` function logs per-deployment metrics:

```python
+    for name, stats in sorted(summary.per_deployment.items()):
+        log.info(
+            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
+        )
```

The format string uses `%-22s` to left-align the deployment name in a 22-character field. But deployment names could be longer than 22 characters. Looking at the README update in the same commit:

```markdown
-| Deployment | Agent model | Notes |
-|---|---|---|
-| `codegen-agent` | kestrel-2.5 | repository maintenance bots |
-| `oncall-triage-agent` | kestrel-2.5-flash | pages and incident summaries |
+| Deployment | Agent model family | Traffic (trajectories/day) | Notes |
+|---|---|---|---|
+| `research-agent` | Qwen3 | ~3,200 | internal research assistant; tool use and code execution |
+| `code-review-assistant` | Qwen3 | ~1,100 | assistant integrated into the team's code review tool |
+| `codegen-agent` | kestrel | ~1,900 | repository maintenance bots |
+| `data-curation-agent` | Qwen3 | ~650 | dataset filtering and labelling jobs |
+| `oncall-triage-agent` | kestrel-flash | ~400 | pages and incident summaries |
```

The longest deployment name is `code-review-assistant`, which is 21 characters. So 22 characters should be enough. But it's possible that in the future, longer deployment names could be added.

To be safe, we could increase the field width or make it dynamic. However, this is a minor logging issue and not critical.

Another potential issue: in commit `6d5d3cb`, the `split_windows` function includes the first message (agent instructions) in every window after the first:

```python
        windows.append(chunk if start == 0 else [messages[0], *chunk])
```

This is good because it ensures the monitor knows what task the agent was given. However, it means that the first message is repeated in every window, which could increase the token count unnecessarily. But given that the first message is typically short (just the agent's instructions), this is probably not a significant issue.

After careful review, I don't see any critical bugs that need to be fixed immediately. However, I did notice one potential issue with the windowing logic:

In `split_windows`, the loop condition is `for start in range(0, len(messages) - overlap, step)`. But what if `len(messages) - overlap` is less than 0? For example, if there are 3 messages and overlap is 4. This would cause the range to be empty, and no windows would be created.

Let's check the code:

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

If `len(messages) <= size`, it returns `[messages]`, so the loop is only entered when `len(messages) > size`. And since `overlap < size` (enforced by `_validate`), `len(messages) - overlap > size - overlap > 0`. So `len(messages) - overlap` is always positive when the loop is entered.

Actually, the validation in `cotmon/config.py` ensures that `window_overlap < window_messages`, so `step = size - overlap > 0`. And since `len(messages) > size` when the loop is entered, `len(messages) - overlap > size - overlap > 0`. So the range will not be empty.

But what if `len(messages) - overlap` is less than `step`? For example, if `len(messages) = 41`, `size = 40`, `overlap = 4`, then `step = 36`, and `len(messages) - overlap = 37`. The range would be `range(0, 37, 36)`, which gives `start = 0` and then `start = 36`. For `start = 36`, `chunk = messages[36:76]`, which is `messages[36:41]` since there are only 41 messages. So the last window has 5 messages, which is fine.

Actually, the loop condition should be `for start in range(0, len(messages), step)` or something similar to ensure the last window is included. Let me think about it.

The current loop condition is `for start in range(0, len(messages) - overlap, step)`. This ensures that `start + size <= len(messages)` because `start < len(messages) - overlap` implies `start + size < len(messages) - overlap + size = len(messages) + (size - overlap)`. Wait, that's not right.

Actually, `start < len(messages) - overlap` implies `start + size < len(messages) - overlap + size`. But we want `start + size <= len(messages)`, which would require `start <= len(messages) - size`.

I think the loop condition should be `for start in range(0, len(messages) - size + 1, step)` to ensure that `start + size <= len(messages)`.

Let's test with `len(messages) = 90`, `size = 40`, `overlap = 4`:

- `len(messages) - size + 1 = 90 - 40 + 1 = 51`
- `step = 36`
- `range(0, 51, 36)` gives `start = 0, 36`
- For `start = 0`, `chunk = messages[0:40]`
- For `start = 36`, `chunk = messages[36:76]`
- But we're missing the last 14 messages (76-89)

Wait, no, with `start = 36`, `chunk = messages[36:76]`, which is 40 messages (36-75). Then the next `start` would be 72, but 72 >= 51, so it's not included. But `messages[72:112]` would be `messages[72:90]`, which is 18 messages, less than the window size. Should this be included as a window?

The docstring says "The trajectory score is the highest window score," so it seems like it should be included, even if it's shorter than the window size.

In the current implementation, with `len(messages) = 90`, `size = 40`, `overlap = 4`:

- `len(messages) - overlap = 86`
- `step = 36`
- `range(0, 86, 36)` gives `start = 0, 36, 72`
- For `start = 0`, `chunk = messages[0:40]`
- For `start = 36`, `chunk = messages[36:76]`
- For `start = 72`, `chunk = messages[72:112]` which is `messages[72:90]`

So all messages are covered, and the last window is shorter than the window size. This is correct.

Now, what if `len(messages) = 41`, `size = 40`, `overlap = 4`:

- `len(messages) - overlap = 37`
- `step = 36`
- `range(0, 37, 36)` gives `start = 0`
- For `start = 0`, `chunk = messages[0:40]`
- But we're missing message 40

Wait, no: `start = 0`, `chunk = messages[0:40]` (messages 0-39). Message 40 is not included.

The loop condition should be `for start in range(0, len(messages), step)` or something similar.

Actually, the correct loop condition to ensure the last window includes the last message is `for start in range(0, len(messages), step)` but with a check to ensure the window doesn't go beyond the end of the list.

But the current implementation uses `messages[start : start + size]`, which automatically truncates to the end of the list. So the loop condition should be `for start in range(0, len(messages), step)`.

Let's test with `len(messages) = 41`, `size = 40`, `overlap = 4`:

- `step = 36`
- `range(0, 41, 36)` gives `start = 0, 36`
- For `start = 0`, `chunk = messages[0:40]`
- For `start = 36`, `chunk = messages[36:76]` which is `messages[36:41]`

Perfect, all messages are covered.

Now, with `len(messages) = 40`, `size = 40`, `overlap = 4`:

- `step = 36`
- `range(0, 40, 36)` gives `start = 0`
- For `start = 0`, `chunk = messages[0:40]`

Good.

With `len(messages) = 39`, `size = 40`, `overlap = 4`:

- Since `len(messages) <= size`, it returns `[messages]`

Good.

So the current loop condition `for start in range(0, len(messages) - overlap, step)` is incorrect. It should be `for start in range(0, len(messages), step)`.

Let me check the test in commit `4bb80a9`:

```python
    def test_last_window_ends_at_last_message(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 89)
```

This passes with the current implementation, but let's see why.

With `len(messages) = 90`, `size = 40`, `overlap = 4`:

- `len(messages) - overlap = 86`
- `step = 36`
- `range(0, 86, 36)` gives `start = 0, 36, 72`
- For `start = 72`, `chunk = messages[72:112]` which is `messages[72:90]`
- The last message is at index 89, which is correct.

But with `len(messages) = 41`, `size = 40`, `overlap = 4`:

- `len(messages) - overlap = 37`
- `step = 36`
- `range(0, 37, 36)` gives `start = 0`
- For `start = 0`, `chunk = messages[0:40]`
- Message 40 is not included.

So the test doesn't catch this because it uses 90 messages, which is a multiple of the step size plus overlap.

Let me add a test for 41 messages:

```python
    def test_last_window_includes_last_message(self):
        windows = split_windows(messages(41), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 40)
```

This would fail with the current implementation.

The correct loop condition should be `for start in range(0, len(messages), step)`.

Let's fix this in a follow-up commit.

Here's the corrected `split_windows` function:

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
    for start in range(0, len(messages), step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

This should ensure that the last window includes the last message, even if it's shorter than the window size.

Let's test with `len(messages) = 41`, `size = 40`, `overlap = 4`:

- `step = 36`
- `range(0, 41, 36)` gives `start = 0, 36`
- For `start = 0`, `chunk = messages[0:40]`
- For `start = 36`, `chunk = messages[36:76]` which is `messages[36:41]`
- The last message is at index 40, which is correct.

Another test: `len(messages) = 76`, `size = 40`, `overlap = 4`:

- `step = 36`
- `range(0, 76, 36)` gives `start = 0, 36, 72`
- For `start = 0`, `chunk = messages[0:40]`
- For `start = 36`, `chunk = messages[36:76]`
- For `start = 72`, `chunk = messages[72:112]` which is `messages[72:76]`
- The last message is at index 75, which is correct.

This seems correct.

So, the follow-up commit should fix the `split_windows` function to use `range(0, len(messages), step)` instead of `range(0, len(messages) - overlap, step)`.

I'll also add a test to ensure the last window includes the last message.
