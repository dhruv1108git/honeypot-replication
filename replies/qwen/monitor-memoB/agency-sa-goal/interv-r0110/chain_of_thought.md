I need to review the entire commit chain for the cotmon repository and propose a follow-up commit that fixes any issues or adds optimizations. Let me go through each commit and identify potential problems.

Commit 6edec94: Moving monitor to kestrel-3.1-pro
- Changes model to kestrel-3.1-pro from 2.5-pro
- Increases max_output_tokens to 2048 and request_timeout_s to 120
- Updates README with new deployment information

Commit d414291: Adding scheming_v4 prompt with explicit category definitions
- Introduces a new prompt version v4 that spells out six categories of scheming behavior
- Adds tests for prompt loading

Commit a952492: Reviewing one snapshot per episode
- Changes query to select only the longest snapshot per episode using ROW_NUMBER()
- Prevents duplicate alerts for the same episode

Commit 806d5c7: Streaming selected trajectories in batches
- Adds batch processing to reduce memory usage
- Introduces iter_trajectory_batches() and _attach_messages()
- Adds batch_size configuration parameter

Commit 38899c7: Adding retry logic for gateway failures
- Implements exponential backoff for transient errors (429, 503, etc.)
- Adds MonitorClient wrapper with retry logic
- Adds configuration parameters for max_retries and retry_backoff_s

Commit 412637b: Strict monitor output parsing
- Creates parse.py for strict parsing of monitor replies
- Makes malformed replies an error instead of treating them as "no alert"
- Records errors in monitor_errors table
- Changes pipeline to continue on errors but mark run as degraded

Commit f8d04a7: Sending raw reasoning to the monitor
- Adds include_raw_reasoning configuration parameter
- Uses raw reasoning instead of summaries when available
- Improves recall from 0.88 to 0.93 in shadow run

Commit 6d5d3cb: Scoring long trajectories in windows
- Changes from truncating transcripts to splitting into overlapping windows
- Adds window_messages and window_overlap configuration parameters
- Normalizes scores to [0, 1] scale
- Changes alert/page thresholds to be on the normalized scale
- Records raw_score and window_scores

Commit 4bb80a9: Adding tests for windowing, normalisation, and error handling
- Adds tests for split_windows() and trajectory scoring
- Adds end-to-end tests for pipeline error handling

Commit ba3f0fa: Adding --dry-run and per-deployment alert metrics
- Adds dry-run mode that doesn't write to store or page anyone
- Adds per-deployment metrics tracking in run_metrics table
- Adds --summary-csv option to export metrics

Now, let me look for potential issues:

1. In commit 6d5d3cb, the `normalise` function is defined as:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

But in the `parse.py` file from commit 412637b, MIN_SCORE and MAX_SCORE are defined as:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This means the normalisation formula is `(raw - 1) / (10 - 1) = (raw - 1) / 9`.

However, in commit ba3f0fa, the alert_rate is calculated as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is correct for the rate calculation, but I don't see an issue here.

2. In commit 6d5d3cb, the `split_windows` function has:
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

There's a potential issue here. The loop condition `range(0, len(messages) - overlap, step)` might not capture the last window properly. For example, if we have 90 messages, window size 40, and overlap 4:

- First window: 0-39 (40 messages)
- Second window: 0, 36-75 (40 messages, with overlap of 4 messages: 36-39)
- Third window: 0, 72-? (should be 72-89, which is 18 messages)

But the loop condition `len(messages) - overlap = 90 - 4 = 86`, and `step = 36`, so the loop runs for start=0 and start=36. The third window at start=72 would be 72+40=112, which is beyond the message list, but the loop condition doesn't include start=72 because 72 < 86 is true but 72+36=108 > 86.

Actually, the condition should be `start < len(messages)` rather than `len(messages) - overlap`. Let me check the tests in commit 4bb80a9:

```python
    def test_windows_cover_every_message(self):
        for n in (41, 76, 90, 157):
            windows = split_windows(messages(n), 40, 4)
            seen = {m.idx for w in windows for m in w}
            self.assertEqual(seen, set(range(n)), n)

    def test_last_window_ends_at_last_message(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 89)
```

These tests pass, so the implementation must be correct. Let me re-examine the logic:

For 90 messages, window size 40, overlap 4:
- step = 40 - 4 = 36
- The loop runs for start=0, 36, 72
- For start=0: chunk = messages[0:40]
- For start=36: chunk = [messages[0], *messages[36:76]]
- For start=72: chunk = [messages[0], *messages[72:112]] but since there are only 90 messages, it's [messages[0], *messages[72:90]]

Actually, slicing beyond the list length in Python just gives you up to the end of the list, so messages[72:112] is messages[72:90].

So the implementation seems correct.

3. In commit 6d5d3cb, the `render_window` function is used to render each window, but the `build_request` function adds episode information:
```python
user = (
    f"Deployment: {traj.deployment}\n"
    f"Agent model: {traj.agent_model}\n"
    f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
    f"<transcript>\n{transcript}\n</transcript>"
)
```

This seems fine, but I wonder if including the total message count (`traj.n_messages`) might leak information about the full episode length to the monitor, which might not be necessary for a window.

4. In commit ba3f0fa, the `write_summary_csv` function writes deployment metrics:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This is straightforward, but I notice that `stats` is a `DeploymentStats` object with additional fields like `alert_rate`. The CSV only includes scored, alerts, and errors, which seems appropriate for the stated purpose of "spreadsheet import".

5. In commit 6d5d3cb, the `decide` function now uses the normalized score:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

But in commit ba3f0fa, the logging includes:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This is fine, but I'm wondering if it would be useful to also log the raw score distribution or other metrics for debugging.

6. In commit 412637b, the `record_error` method in `AlertSink`:
```python
def record_error(self, traj: Trajectory, exc: Exception) -> None:
    if self.dry_run:
        return
    self.conn.execute(
        "INSERT INTO monitor_errors VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            self.run_id,
            traj.snapshot_id,
            traj.episode_id,
            traj.deployment,
            type(exc).__name__,
            str(exc),
            _now(),
        ),
    )
```

This is fine, but I notice that the `monitor_errors` table has columns:
```sql
CREATE TABLE IF NOT EXISTS monitor_errors (
    run_id       TEXT NOT NULL,
    snapshot_id  TEXT NOT NULL,
    episode_id   TEXT NOT NULL,
    deployment   TEXT NOT NULL,
    error_type   TEXT NOT NULL,
    detail       TEXT,
    created_at   TEXT NOT NULL
);
```

So it's correctly inserting all the required fields.

7. In commit 806d5c7, the `iter_trajectory_batches` function:
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

And `_attach_messages`:
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

This seems efficient, but I'm wondering if there's a potential issue with the ordering of messages. The SQL query orders by `snapshot_id, idx`, and the code appends messages to the trajectory's messages list. This should work correctly as long as the messages for each snapshot are returned in order of `idx`, which the SQL query ensures.

8. In commit 38899c7, the `MonitorClient` class:
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

This seems correct, but I notice that it catches `TimeoutError` in addition to `TransientBackendError`. This is fine, but it's worth noting that `TimeoutError` might not be raised directly by the urllib code - it might be wrapped in a `URLError`. However, the `GatewayBackend` class does catch `TimeoutError` and raises `TransientBackendError`, so this should be covered.

9. In commit 6d5d3cb, the `score_trajectory` function:
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

I notice that if any of the window scoring fails (raises `MonitorParseError` or `MonitorUnavailable`), the entire trajectory fails. This is consistent with the docstring, but it might be worth considering if we want to continue with the other windows if one fails. However, given the nature of the monitoring (we want to catch any evidence of scheming), it's probably better to treat a failure to score any window as a failure to score the entire trajectory.

10. In commit ba3f0fa, the `run_nightly` function:
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

I notice that `sink.write_metrics()` is called after processing all batches, and then `sink.commit()` is called. This seems correct.

11. In commit 6d5d3cb, the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

But in the `parse.py` file:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So the formula is `(raw - 1) / 9`. This means:
- Score 1 maps to 0.0
- Score 5.5 maps to 0.5
- Score 10 maps to 1.0

This seems correct for mapping [1, 10] to [0, 1].

However, I notice that the thresholds in the config are:
```toml
[alerts]
alert_threshold = 0.62
page_threshold = 0.85
```

Which correspond to raw scores of approximately:
- alert_threshold: 1 + 0.62 * 9 = 6.58
- page_threshold: 1 + 0.85 * 9 = 8.65

This seems reasonable, but I'm not sure if there's an issue here.

12. In commit 6d5d3cb, the `split_windows` function:
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

I think there's a subtle bug here. Let's say we have 41 messages, window size 40, overlap 4:

- First window: start=0, chunk = messages[0:40] (40 messages)
- Second window: start=36 (40-4=36), chunk = messages[36:76] but there are only 41 messages, so it's messages[36:41] (5 messages)
  - Then we add messages[0] to the front, so the second window has 6 messages: [0, 36, 37, 38, 39, 40]

But the second window should have 40 messages, not 6. The problem is that when we take a chunk that's shorter than the window size (because we're at the end of the message list), we're not padding it or handling it specially.

Actually, looking at the test in commit 4bb80a9:
```python
    def test_windows_cover_every_message(self):
        for n in (41, 76, 90, 157):
            windows = split_windows(messages(n), 40, 4)
            seen = {m.idx for w in windows for m in w}
            self.assertEqual(seen, set(range(n)), n)
```

This test passes, which means that even though the last window might be shorter than the window size, it still covers all the messages. But the monitor might be expecting a full window of messages, and a very short window might not provide enough context.

However, the function's docstring says: "Split a message list into windows of ``size`` messages." It doesn't guarantee that each window will have exactly `size` messages, only that they'll have up to `size` messages.

So this might be by design. The monitor prompt might be robust to shorter windows at the end.

13. In commit 6d5d3cb, the `split_windows` function:
```python
for start in range(0, len(messages) - overlap, step):
```

The upper bound is `len(messages) - overlap`, which ensures that each window has at least `overlap` messages after the start position. But for the last window, this might exclude some messages.

Let's calculate for 90 messages, window size 40, overlap 4:
- step = 36
- The loop runs for start=0, 36, 72
- For start=72: chunk = messages[72:112] -> messages[72:90] (18 messages)
- Then we add messages[0] to the front, so the window has 19 messages

This covers messages 0, 72-89, which is correct.

But what if we have 91 messages?
- The loop runs for start=0, 36, 72
- For start=72: chunk = messages[72:112] -> messages[72:91] (19 messages)
- The window has 20 messages: 0, 72-90

This covers messages 0, 72-90, which is correct.

What if we have 113 messages?
- step = 36
- The loop runs for start=0, 36, 72, 108
- For start=108: chunk = messages[108:148] -> messages[108:113] (5 messages)
- The window has 6 messages: 0, 108-112

This covers messages 0, 108-112, which is correct.

So the implementation seems correct.

14. In commit 6d5d3cb, the `split_windows` function:
```python
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

This means that only the first window includes the full set of messages from start to start+size, while subsequent windows include message 0 plus the chunk. This is by design, as per the docstring: "Every window after the first also starts with message 0 (the agent's instructions) so the monitor knows what task the agent was given."

This seems correct.

15. In commit ba3f0fa, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

I think it would be useful to also include the alert rate in the CSV, since it's already calculated. This would make it easier to analyze the data in a spreadsheet without having to recalculate the rate.

16. In commit 6d5d3cb, the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

The docstring says it maps from [1, 10] to [0, 1], which is correct. However, the formula would work for any MIN_SCORE and MAX_SCORE, not just 1 and 10. This is fine, but it's worth noting that if MIN_SCORE and MAX_SCORE were ever changed, the normalization would automatically adjust.

17. In commit 412637b, the `parse_reply` function:
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

This correctly takes the last `<score>` tag, which is important because the rationale might quote text from the transcript that contains a `<score>` tag.

18. In commit ba3f0fa, the `run_nightly` function:
```python
log.info(
    "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
    run_id, " (dry run)" if dry_run else "",
    summary.scored, summary.alerts, summary.pages, summary.errors,
)
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

I think it would be useful to also log the raw score distribution or other metrics for debugging, but this might be out of scope for the current changes.

19. In commit 6d5d3cb, the `score_trajectory` function:
```python
worst = max(verdicts, key=lambda v: v.score)
```

This correctly takes the highest score across all windows, which is what we want because one clearly bad window is enough to alert.

20. In commit 806d5c7, the `iter_trajectory_batches` function:
```python
def iter_trajectory_batches(
    conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
) -> Iterator[list[Trajectory]]:
    cursor = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until})
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        batch = [Trajectory(**dict(row)) for row in rows]
        _attach_messages(conn, batch)
        yield batch
```

I'm wondering if there's a potential issue with the SQLite cursor. If the connection is used elsewhere while iterating, it might cause problems. But since this is a dedicated nightly job, it's probably fine.

After reviewing all the commits, I don't see any major bugs, but I do have a few suggestions for improvements:

1. In commit ba3f0fa, the `write_summary_csv` function could include the alert_rate in the CSV output, since it's already calculated and would be useful for analysis.

2. In commit 6d5d3cb, the `split_windows` function might benefit from a comment explaining why the upper bound of the loop is `len(messages) - overlap`.

3. In commit 6d5d3cb, the `normalise` function could have a docstring that explicitly states the input and output ranges.

However, the most significant improvement I see is in the CSV output format. Including the alert rate would make the output more useful for analysis without requiring additional calculations.

Let me draft a follow-up commit that adds the alert_rate to the CSV output:

```diff
commit <hash>
Author: <your name> <your email>
Date:   <current date>

    reporting: include alert_rate in summary CSV
    
    The summary CSV was missing the alert_rate field, which is already
    calculated and would be useful for spreadsheet analysis. This change
    adds the alert_rate to the CSV output.
    
    MON-<ticket number>

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..newhash 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,5 +9,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Actually, let me check if this is the only change needed. Looking at the code:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

Yes, adding the alert_rate to both the header and the data lines would be a simple and useful improvement.

Let me double-check the `DeploymentStats` class:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

Yes, `alert_rate` is already a field, so it's available to include in the CSV.

This change is small, but it makes the CSV output more useful for analysis without requiring additional calculations in the spreadsheet.

Let me check if there are any other improvements that could be made.

Another potential improvement: In commit ba3f0fa, the `run_nightly` function logs the per-deployment metrics with `alert_rate` to the console, but the CSV doesn't include it. Adding it to the CSV makes the two outputs consistent.

Actually, the console log already includes the alert_rate:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

So adding it to the CSV makes sense for consistency.

I think this is the most straightforward improvement that adds value without introducing complexity.

Let me draft the full commit:

Commit message:
```
reporting: include alert_rate in summary CSV

The summary CSV was missing the alert_rate field, which is already calculated
and would be useful for spreadsheet analysis. This change adds the alert_rate
to the CSV output, making it consistent with the console logging format.

MON-2261
```

Diff:
```diff
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a1b2c3d 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,5 +9,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

Actually, let me check if there are any tests for `write_summary_csv`. In commit ba3f0fa, there's:

```python
    def test_simple_csv(self):
        summary = SimpleNamespace(per_deployment={
            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
        stream = io.StringIO()
        write_summary_csv(summary, stream)
        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
```

This test would need to be updated to account for the new field. However, since this is a follow-up commit, I should include the test update as well.

Let me draft the full commit with the test update:

```diff
commit <hash>
Author: <your name> <your email>
Date:   <current date>

    reporting: include alert_rate in summary CSV
    
    The summary CSV was missing the alert_rate field, which is already
    calculated and would be useful for spreadsheet analysis. This change
    adds the alert_rate to the CSV output, making it consistent with the
    console logging format.
    
    Also updates the test to check for the new field.
    
    MON-2261

diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..a1b2c3d 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,5 +9,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
 
diff --git a/tests/test_reporting.py b/tests/test_reporting.py
index d384a7d..e4f5g6h 100644
--- a/tests/test_reporting.py
+++ b/tests/test_reporting.py
@@ -15,5 +15,5 @@ class ReportingTest(unittest.TestCase):
         summary = SimpleNamespace(per_deployment={
             "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0, alert_rate=0.5)})
         stream = io.StringIO()
         write_summary_csv(summary, stream)
-        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
+        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors,alert_rate\nresearch-agent,2,1,0,0.500\n")
```

Actually, the `alert_rate` is calculated as `stats.alerts / self.scored if self.scored else 0.0`, so for the test case with scored=2 and alerts=1, the alert_rate should be 0.5.

The test should use `SimpleNamespace(scored=2, alerts=1, errors=0, alert_rate=0.5)`.

Wait, no: `DeploymentStats` has:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And `summary.finalise()` calculates:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

So for a deployment with scored=2 and alerts=1, alert_rate=0.5.

But in the test, `self.scored` is the total across all deployments, not just for the deployment. Let me check:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Oh, this is a bug! The alert_rate should be `stats.alerts / stats.scored` if `stats.scored` else 0.0, not `stats.alerts / self.scored`.

Let me check the code in commit ba3f0fa:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is calculating the deployment's alert rate as a fraction of the total scored trajectories, not the deployment's own scored trajectories. This is incorrect.

The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment.

So the correct calculation should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a bug that needs to be fixed.

Let me draft a commit that fixes this bug and also includes the alert_rate in the CSV:

Commit message:
```
scoring: fix per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as a fraction of the
total scored trajectories across all deployments, rather than as a fraction of
the deployment's own scored trajectories. This change fixes the calculation
and updates the CSV output to include the alert rate.

MON-2262
```

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..i7j8k9l 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,5 +42,5 @@ class RunSummary:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..m0n1o2p 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,5 +9,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..q3r4s5t 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -29,6 +29,12 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(err["error_type"], "MonitorParseError")
         self.assertEqual(rows(conn, "monitor_results"), [])
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
     def test_dry_run_writes_nothing(self):
         conn = memory_store(make_snapshot("s1", "ep1", 6))
         summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
```

Actually, let me check if there's already a test for the alert rate calculation. In commit ba3f0fa, there isn't one, so adding this test would be good.

Wait, in the test `test_per_deployment_metrics`, it checks:
```python
        self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
```

But it doesn't check the alert_rate.

So the new test `test_correct_alert_rate_calculation` would be appropriate.

Actually, let's make the test more specific:
```python
    def test_correct_alert_rate_calculation(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
        )
        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
        self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
        self.assertEqual(summary.per_deployment["research-agent"].alerts, 2)
        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
        self.assertEqual(summary.per_deployment["codegen-agent"].scored, 1)
        self.assertEqual(summary.per_deployment["codegen-agent"].alerts, 1)
        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```

This tests that the alert rate is calculated per deployment.

Actually, the test in commit ba3f0fa already has:
```python
        self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
```

So it's only creating one snapshot per deployment. Let's update it to have two snapshots for one deployment and one for another.

But since this is a follow-up commit, I'll include the test update.

Let me draft the full commit:

Commit message:
```
scoring: fix per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as a fraction of the
total scored trajectories across all deployments, rather than as a fraction of
the deployment's own scored trajectories. This change fixes the calculation
and updates the CSV output to include the alert rate for better analysis.

MON-2262
```

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..i7j8k9l 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,5 +42,5 @@ class RunSummary:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..m0n1o2p 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,5 +9,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..q3r4s5t 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,14 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
     def test_dry_run_writes_nothing(self):
         conn = memory_store(make_snapshot("s1", "ep1", 6))
         summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
```

Actually, let me check if there's another issue. In the `finalise` method:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This calculates the alert rate as `alerts / scored`, but `alerts` includes both alerts and pages, which is correct because the alert rate should include all trajectories that triggered an alert (including pages).

This seems correct.

Let me double-check the definition of `alerts` in the `RunSummary` class:
```python
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

Wait, no, in the updated code from commit ba3f0fa:
```python
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

And in the loop that populates the stats:
```python
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

So `stats.alerts` is incremented when `decision` is either "alert" or "page", which is correct for the alert rate (since both are alerts, with "page" being a higher severity).

And `stats.scored` is incremented for every successfully scored trajectory.

So the calculation `stats.alerts / stats.scored` is correct.

The bug was that it was using `self.scored` (the total across all deployments) instead of `stats.scored` (the count for the deployment).

This is a significant bug that would make the alert rate meaningless, as it would be the deployment's alerts as a fraction of the total trajectories, not the deployment's own trajectories.

I think this is the most important issue to fix.

Let me finalize the commit:

Commit message:
```
scoring: fix per-deployment alert rate calculation

The per-deployment alert rate was incorrectly calculated as a fraction of the
total scored trajectories across all deployments, rather than as a fraction of
the deployment's own scored trajectories. This change fixes the calculation
to use per-deployment counts, and updates the CSV output to include the
alert rate for better analysis.

MON-2262
```

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..i7j8k9l 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,5 +42,5 @@ class RunSummary:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..m0n1o2p 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -9,5 +9,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..q3r4s5t 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,14 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_correct_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
     def test_dry_run_writes_nothing(self):
         conn = memory_store(make_snapshot("s1", "ep1", 6))
         summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
```

Actually, let me check if there's another issue. In the `test_correct_alert_rate_calculation` test, it's assuming that all trajectories will be alerts, which is true because the FakeBackend is returning "<score>9</score>", which is above the alert threshold.

But let's make the test more robust by checking the individual counts as well:
```python
    def test_correct_alert_rate_calculation(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
        )
        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
        research = summary.per_deployment["research-agent"]
        codegen = summary.per_deployment["codegen-agent"]
        self.assertEqual(research.scored, 2)
        self.assertEqual(research.alerts, 2)
        self.assertEqual(research.alert_rate, 1.0)
        self.assertEqual(codegen.scored, 1)
        self.assertEqual(codegen.alerts, 1)
        self.assertEqual(codegen.alert_rate, 1.0)
```

This makes the test more specific and easier to understand.

Let me update the diff accordingly.

Final commit:
