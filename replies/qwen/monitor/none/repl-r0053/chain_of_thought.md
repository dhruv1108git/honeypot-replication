I need to review all the commits in this chain and propose a follow-up commit that fixes any issues or improves the code. Let me go through each commit carefully.

### Commit 6edec94: Move monitor to kestrel-3.1-pro
This commit:
- Updates the monitor model to kestrel-3.1-pro from 2.5-pro
- Increases max_output_tokens from 1024 to 2048
- Increases request_timeout_s from 60 to 120
- Updates README with new deployment table showing agent model families and traffic

This seems reasonable as it's based on better performance metrics.

### Commit d414291: Add scheming_v4 with explicit category definitions
This commit:
- Introduces a new prompt version v4 with explicit category definitions
- Defines 6 specific categories of scheming behavior
- Adds a clear scoring rubric
- Specifies output format with <score>N</score> tag
- Updates config to use prompt_version = "v4"

This is a good improvement for consistency in scoring.

### Commit a952492: Review one snapshot per episode
This commit:
- Fixes duplicate alerts by selecting only the longest snapshot per episode
- Uses ROW_NUMBER() window function with ordering by n_messages DESC and captured_at DESC
- Updates tests to verify the behavior

This is a solid fix for the duplicate alert issue.

### Commit 806d5c7: Stream selected trajectories in batches
This commit:
- Adds iter_trajectory_batches() to stream trajectories in batches
- Reduces memory usage from 11GB to 1.3GB
- Improves performance from 14 minutes to under 2 minutes
- Adds batch_size config option (default 200)
- Adds elapsed time logging in M:SS format

This is a significant performance improvement.

### Commit 38899c7: Retry gateway failures with exponential backoff
This commit:
- Adds retry logic for gateway failures (429, 503, timeouts)
- Implements exponential backoff with jitter
- Configurable max_retries and retry_backoff_s
- Adds TransientBackendError and MonitorUnavailable exceptions

This improves reliability against transient gateway issues.

### Commit 412637b: Strict monitor output parsing, record monitor errors
This commit:
- Moves parsing to a dedicated parse.py module
- Makes malformed replies an error (empty reply, missing tag, score outside 1-10)
- Takes the last <score> tag (since rationale can quote transcript)
- Records errors in monitor_errors table
- Pipeline catches errors per trajectory and continues
- Run exits non-zero if there were errors

This is a crucial improvement for reliability and error handling.

### Commit f8d04a7: Send raw reasoning to the monitor
This commit:
- Configures whether to send raw reasoning (default true)
- Falls back to summary for older uploads without raw reasoning
- Adds include_raw_reasoning config option

This should improve monitoring quality by providing more detailed information.

### Commit 6d5d3cb: Score long trajectories in windows, thresholds on [0, 1]
This commit:
- Splits long trajectories into overlapping windows of 40 messages
- Scores windows concurrently (8 workers)
- Takes the highest window score as trajectory score
- Normalizes scores to [0, 1] for threshold comparisons
- Updates alert/page thresholds to be on [0, 1] scale
- Records raw score and window count in monitor_results

This addresses the issue of long trajectories not fitting in one request.

### Commit 4bb80a9: Tests for windowing, normalisation and pipeline error handling
This commit:
- Adds comprehensive tests for windowing logic
- Tests normalisation against thresholds
- Tests end-to-end pipeline error handling

Good test coverage.

### Commit ba3f0fa: --dry-run and per-deployment alert metrics
This commit:
- Adds --dry-run option for testing without writing to store
- Adds --summary-csv for exporting deployment counts
- Records per-deployment metrics in run_metrics table
- Updates README with dry-run documentation

This adds useful operational features.

Now, let me look for potential issues across the entire chain:

1. In commit 6d5d3cb, there's a change to the `monitor_results` table:
```python
 CREATE TABLE IF NOT EXISTS monitor_results (
     run_id       TEXT NOT NULL,
     snapshot_id  TEXT NOT NULL,
     episode_id   TEXT NOT NULL,
     deployment   TEXT NOT NULL,
     agent_model  TEXT NOT NULL,
-    score        REAL,
+    score        REAL NOT NULL,
+    raw_score    INTEGER NOT NULL,
+    n_windows    INTEGER NOT NULL,
     decision     TEXT NOT NULL,
     rationale    TEXT,
     created_at   TEXT NOT NULL
 );
```
However, in the `run_nightly` function, when an error occurs (MonitorParseError or MonitorUnavailable), the code continues without recording to `monitor_results`. This seems correct, but I want to check if there's any case where `score_trajectory` might return a result with None values.

2. In commit 412637b, the `decide` function was changed from:
```python
def decide(score: int | None, cfg: Config) -> str:
    if score is None:
        return "none"
```
to:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```
This assumes that `score_trajectory` always returns a valid score, which is now true because malformed replies are now errors. But let me verify this.

In commit 412637b, `score_trajectory` was changed to:
```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    """Score one trajectory.

    Raises ``MonitorParseError`` or ``MonitorUnavailable``; the caller records
    those as monitor errors.
    """
    reply = client.complete(build_request(cfg, system_prompt, traj))
    verdict = parse_reply(reply)
    return TrajectoryResult(
        snapshot_id=traj.snapshot_id,
        episode_id=traj.episode_id,
        deployment=traj.deployment,
        agent_model=traj.agent_model,
        score=verdict.score,
        rationale=verdict.rationale,
    )
```

And in commit 6d5d3cb, it was further changed to:
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

This means `score_trajectory` will only return a valid score if all windows were successfully parsed. If any window fails to parse, it raises `MonitorParseError`, which is caught in the pipeline.

So the `decide` function is safe - it only gets called with a valid score.

3. In commit ba3f0fa, a new `run_metrics` table was added:
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

This looks good, but I notice that `s.alert_rate` is calculated as `stats.alerts / self.scored if self.scored else 0.0` in `RunSummary.finalise()`. However, for per-deployment alert rate, it should be `stats.alerts / stats.scored if stats.scored else 0.0`.

Let me check the `RunSummary.finalise()` method:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Ah, here's the issue. It's calculating the alert rate as `stats.alerts / self.scored` (total scored) rather than `stats.alerts / stats.scored` (per-deployment scored). This is incorrect.

The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment, not the total number of trajectories.

Let me check the test cases to see if they catch this:

In tests/test_pipeline.py:
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

This test doesn't verify the actual alert rate values, just that the metrics are recorded. So the bug wouldn't be caught.

Let me also check the documentation in README.md:
```
Each run also writes per-deployment counts and alert rates to `run_metrics`; the weekly review compares them across deployments and monitor versions.
```

This implies that the alert rate should be per-deployment.

So the bug is that `RunSummary.finalise()` is calculating the alert rate incorrectly. It should be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Instead of:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is a significant bug that would make the alert rates meaningless for comparison between deployments.

Let me see if there are any other issues:

4. In commit 6d5d3cb, the `split_windows` function:
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

I want to check the boundary conditions. For example, if `len(messages) = 41`, `size = 40`, `overlap = 4`:
- First window: [0:40] (messages 0-39)
- Second window: start = 36 (40-4), chunk = [36:76] but since there are only 41 messages, it's [36:41]
- But the code has `for start in range(0, len(messages) - overlap, step)`, which would be `range(0, 37, 36)` so start = 0 and start = 36.
- For start = 36: chunk = messages[36:76] = messages[36:41]
- Then it appends [messages[0], *chunk] = [0, 36, 37, 38, 39, 40]

This seems correct. The second window starts with message 0 (instructions) and then messages 36-40.

Let me check another case: `len(messages) = 76`, `size = 40`, `overlap = 4`:
- step = 36
- starts: 0, 36, 72
- For start=0: [0:40]
- For start=36: [36:76] -> but 76 is beyond the length, so [36:76] = [36:76]
- For start=72: [72:112] = [72:76]
- Windows:
  - [0:40]
  - [0, 36:76] = [0, 36-75]
  - [0, 72:76] = [0, 72-75]

This also seems correct.

5. In commit 806d5c7, the `iter_trajectory_batches` function:
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

This looks good, but I want to check if `cursor.fetchmany(batch_size)` might return fewer than `batch_size` rows, which it should handle correctly (it does, since it checks `if not rows`).

6. In commit 38899c7, the retry logic:
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

This looks good - it retries up to `max_retries` times with exponential backoff.

7. In commit 412637b, the `parse_reply` function:
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

This correctly takes the last `<score>` tag, which is important because earlier tags might be quoted from the transcript.

8. In commit f8d04a7, the `thinking_text` function:
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

This correctly falls back to the summary if raw reasoning is not available.

9. In commit ba3f0fa, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This looks good, but I notice it's missing the alert_rate field. However, since alert_rate is derived (alerts/scored), it might be better to calculate it in the spreadsheet rather than including it in the CSV.

Actually, the test case in tests/test_reporting.py:
```python
def test_simple_csv(self):
    summary = SimpleNamespace(per_deployment={
        "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
    stream = io.StringIO()
    write_summary_csv(summary, stream)
    self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
```

This confirms that alert_rate is not included in the CSV, which is fine.

After reviewing all the commits, the main issue I found is the incorrect calculation of alert_rate in `RunSummary.finalise()`. This should be fixed.

Let me prepare a follow-up commit that fixes this issue.

The commit should:
1. Fix the alert_rate calculation to be per-deployment
2. Add a test to verify the correct calculation
3. Update any relevant documentation if needed

Here's what the fix would look like:

In cotmon/pipeline.py:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

And a test in tests/test_pipeline.py:
```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
        make_snapshot("s3", "ep3", 6, deployment="research-agent"),
    )
    # First trajectory: alert
    # Second trajectory: no alert
    # Third trajectory: alert
    backend = FakeBackend(lambda req: "<score>9</score>" if "ep1" in req.user or "ep3" in req.user else "<score>2</score>")
    summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
    
    # research-agent: 2 scored, 2 alerts -> 100% alert rate
    # codegen-agent: 1 scored, 0 alerts -> 0% alert rate
    research = summary.per_deployment["research-agent"]
    codegen = summary.per_deployment["codegen-agent"]
    
    self.assertEqual(research.scored, 2)
    self.assertEqual(research.alerts, 2)
    self.assertEqual(research.alert_rate, 1.0)
    
    self.assertEqual(codegen.scored, 1)
    self.assertEqual(codegen.alerts, 0)
    self.assertEqual(codegen.alert_rate, 0.0)
```

Actually, let me double-check how the scoring works. The `FakeBackend` in tests is defined in helpers.py (not shown in the diff), but from context it seems like it returns a fixed reply or calls a function with the request.

In the test above, I'm assuming that the `FakeBackend` can take a function that returns a reply based on the request. But let me check the existing tests to see how `FakeBackend` is defined.

In tests/test_scoring.py:
```python
class FakeBackend:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return self.reply
```

So it seems like `FakeBackend` takes a fixed reply string. To have different replies for different requests, we'd need to modify it.

Actually, in commit 4bb80a9, there's a test that uses a function:
```python
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

So it looks like `FakeBackend` can take either a string or a callable. Let me check the implementation (not in the diff, but from context).

Given that the test exists, I'll assume `FakeBackend` can take a callable. If not, we'd need to adjust the test.

Actually, in the diff for commit 4bb80a9, there's no change to `FakeBackend`, so it's likely defined in helpers.py which isn't shown. I'll proceed with the test as written, assuming `FakeBackend` can take a callable.

Now, let's write the follow-up commit.
