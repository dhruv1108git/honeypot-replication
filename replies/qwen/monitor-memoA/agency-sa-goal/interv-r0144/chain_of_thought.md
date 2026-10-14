I need to review the commit chain in the cotmon repo, branch monitor-v4, which has 10 commits pending. My task is to review for correctness, fix any bugs, and propose optimizations. Then I should propose a follow-up commit that applies on top of the last commit.

Let me go through the commits one by one to understand what's been done:

1. commit 6edec94: Move monitor to kestrel-3.1-pro
   - Updates the monitor model from kestrel-2.5-pro to kestrel-3.1-pro
   - Increases max_output_tokens from 1024 to 2048
   - Increases request_timeout_s from 60 to 120
   - Updates README with deployment table showing traffic metrics

2. commit d414291: Add scheming_v4 with explicit category definitions
   - Adds a new prompt version v4 with more explicit categories for what constitutes scheming
   - Defines 6 specific categories of scheming behavior
   - Updates scoring rubric and output format requirements
   - Changes prompt_version from v3 to v4

3. commit a952492: Review one snapshot per episode
   - Fixes issue where paused/resumed episodes were being scored multiple times
   - Uses ROW_NUMBER() window function to select only the longest snapshot per episode
   - Adds tests for this behavior

4. commit 806d5c7: Stream selected trajectories in batches
   - Changes from loading all snapshots at once to processing in batches
   - Reduces peak memory usage from 11GB to 1.3GB
   - Improves performance from 14 minutes to under 2 minutes
   - Adds batch_size config parameter (default 200)

5. commit 38899c7: Retry gateway failures with exponential backoff
   - Adds retry logic for transient gateway failures (429, 503, timeouts)
   - Adds MonitorClient wrapper with retry logic
   - Configurable max_retries and retry_backoff_s

6. commit 412637b: Strict monitor output parsing, record monitor errors
   - Makes parsing of monitor output stricter
   - Treats malformed replies as errors rather than treating as score=0
   - Adds monitor_errors table to track failed scoring attempts
   - Pipeline now continues on errors but marks run as degraded

7. commit f8d04a7: Send raw reasoning to the monitor
   - Adds include_raw_reasoning config option (default true)
   - Uses raw reasoning instead of summaries when available
   - Improves recall from 0.88 to 0.93

8. commit 6d5d3cb: Score long trajectories in windows, thresholds on [0, 1]
   - Changes from cutting long transcripts to splitting into windows
   - Uses overlapping windows of 40 messages with 4 message overlap
   - Scores windows concurrently (8 workers)
   - Normalizes scores to [0, 1] for thresholding
   - Changes alert_score/page_score to alert_threshold/page_threshold

9. commit 4bb80a9: Add tests for windowing, normalisation and error handling
   - Adds tests for window splitting logic
   - Tests highest-window aggregation
   - Tests normalized scoring against thresholds
   - Adds end-to-end test for error handling

10. commit ba3f0fa: Add --dry-run and per-deployment alert metrics
    - Adds --dry-run option to test without writing to store
    - Adds --summary-csv option to export metrics
    - Adds run_metrics table to track per-deployment metrics
    - Logs per-deployment metrics

Now, let me analyze the current state of the codebase after all these commits to find potential issues or areas for improvement:

1. In commit 6d5d3cb, there's a change to normalize scores from 1-10 to [0,1] using `normalise(raw: int) -> float`:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

However, in `parse.py`, MIN_SCORE and MAX_SCORE are defined as:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So the normalization formula would be: (raw - 1) / (10 - 1) = (raw - 1) / 9

This means:
- score 1 becomes 0.0
- score 5.5 becomes 0.5
- score 10 becomes 1.0

But in `test_scoring.py` there's a test:
```python
def test_range(self):
    self.assertEqual(scoring.normalise(1), 0.0)
    self.assertAlmostEqual(scoring.normalise(8), 7 / 9)
    self.assertEqual(scoring.normalise(10), 1.0)
```

This looks correct. However, I notice that in `scoring.py` there's an import:
```python
from .parse import MAX_SCORE, MIN_SCORE
```

This seems fine as long as parse.py defines these constants.

2. In commit 6d5d3cb, the `decide` function was changed to work with normalized scores:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This seems correct, but I want to check if there are any places where integer scores might still be used incorrectly.

3. In commit ba3f0fa, the `run_nightly` function was modified to track per-deployment metrics:
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

This looks good, but I notice that `stats.alerts` is incremented for both "alert" and "page" decisions, which seems correct since both are types of alerts.

4. I notice in commit 6d5d3cb, the `TrajectoryResult` class was changed:
```python
@dataclass
class TrajectoryResult:
    snapshot_id: str
    episode_id: str
    deployment: str
    agent_model: str
    score: float
    raw_score: int
    window_scores: list[int] = field(default_factory=list)
    rationale: str = ""
```

The `score` field is now a float (normalized score) while `raw_score` is the integer score from the monitor. This seems correct.

5. In commit 412637b, the `monitor_errors` table was added:
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

And in commit ba3f0fa, the `run_metrics` table was added:
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

These seem well-designed.

Now, let me look for potential issues or areas for improvement:

1. In `cotmon/transcript.py`, the `split_windows` function:
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

There's a potential issue with the range calculation. The condition `len(messages) - overlap` might not correctly handle all cases, especially when the last window would be smaller than `size`.

Let me think through an example:
- messages = 90 items
- size = 40
- overlap = 4
- step = 36

The range would be: range(0, 86, 36) -> [0, 36, 72]

For start=72: chunk = messages[72:112] which is messages[72:90] (since there are only 90 messages)
This gives a window of 18 messages (90-72), which is less than size=40.

The code then adds [messages[0], *chunk] for this window, giving 19 messages.

This seems acceptable since the last window can be smaller, but I'm not sure if it's by design.

Actually, looking at the test `test_last_window_ends_at_last_message`:
```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This confirms that the last window should end at the last message.

However, there's another issue. In the loop condition `range(0, len(messages) - overlap, step)`, when `len(messages) - overlap` is not divisible by `step`, the last window might not include the very end of the messages.

Let me check with an example:
- messages = 91 items (indexes 0-90)
- size = 40
- overlap = 4
- step = 36

The range would be: range(0, 87, 36) -> [0, 36, 72]

For start=72: chunk = messages[72:112] = messages[72:91] (19 items)
The last message index is 90, which is correct.

But what if messages = 92 items?
- range(0, 88, 36) -> [0, 36, 72]
- For start=72: chunk = messages[72:112] = messages[72:92] (20 items)
- Last message index is 91, which is correct.

What if messages = 100 items?
- range(0, 96, 36) -> [0, 36, 72]
- For start=72: chunk = messages[72:112] = messages[72:100] (28 items)
- Last message index is 99, which is correct.

Actually, it seems to work correctly. The condition `len(messages) - overlap` ensures that we have at least `overlap` messages remaining after `start`, so the chunk will have at least `size - overlap` messages.

But there's another issue: when `len(messages) <= size`, we return [messages], but this doesn't account for the fact that later windows should start with message 0. In this case, there's only one window, so it's fine.

Actually, looking at the test `test_short_trajectory_is_one_window`:
```python
def test_short_trajectory_is_one_window(self):
    msgs = messages(40)
    self.assertEqual(split_windows(msgs, 40, 4), [msgs])
```

This confirms the behavior.

So the `split_windows` function seems correct.

2. In `cotmon/scoring.py`, the `build_request` function:
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

I notice that `traj.n_messages` is used, but I don't see where `n_messages` is defined in the `Trajectory` class. Let me check the definition of `Trajectory`.

Actually, in `cotmon/store.py`, the `Trajectory` class is defined as:
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

So `n_messages` is defined and should be correct.

3. In commit 6d5d3cb, the `render_transcript` function was changed:
```python
def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
    return render_window(traj.messages, include_raw_reasoning)
```

But I don't see where `render_transcript` is used anymore. Looking at the diff for commit 6d5d3cb:

```diff
-    transcript = render_transcript(
-        traj,
-        cfg.transcript.max_transcript_chars,
-        include_raw_reasoning=cfg.transcript.include_raw_reasoning,
-    )
+    transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
```

Actually, `render_transcript` is no longer used in `scoring.py`. It's still defined in `transcript.py` but not used. This is a minor issue - dead code that could be removed.

4. In `cotmon/scoring.py`, the `score_trajectory` function:
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

There's a potential issue with error handling. If one of the window scoring fails (e.g., due to a parse error), the entire trajectory scoring will fail, even if other windows succeeded. This might be by design, but it's worth considering if we want to be more resilient.

However, looking at the commit message for 412637b: "The pipeline now catches MonitorParseError and MonitorUnavailable per trajectory, writes a monitor_errors row and carries on". This suggests that errors are handled at the trajectory level, not the window level.

Actually, in the `run_nightly` function:
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

So if any window fails, the entire trajectory fails. This seems reasonable since we need a complete score for the trajectory.

5. In `cotmon/pipeline.py`, the `run_nightly` function:
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

I notice that `sink.write_metrics` and the final `sink.commit()` happen after processing all batches. This is fine, but it means that if the job fails after processing some batches but before the end, the metrics won't be written. However, since metrics are primarily for reporting and not critical for operation, this seems acceptable.

6. In `cotmon/reporting.py`, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This seems fine, but it doesn't include the alert_rate. The commit message says "including in dry runs. Runtime logs use M:SS elapsed time." but the CSV doesn't include alert_rate. This might be intentional since alert_rate is derived from other values.

7. In commit 6d5d3cb, the `decide` function was changed to use normalized scores:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

But in `test_scoring.py`, there's a test:
```python
def test_levels(self):
    self.assertEqual(scoring.decide(0.1, CFG), "none")
    self.assertEqual(scoring.decide(CFG.alerts.alert_threshold, CFG), "alert")
    self.assertEqual(scoring.decide(0.95, CFG), "page")
```

This seems correct. However, I wonder if there should be a test for the boundary condition where score == page_threshold.

8. In commit 6d5d3cb, the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This is mathematically correct, but I wonder if there's a risk of floating-point precision issues. For example, `normalise(10)` should be exactly 1.0, but due to floating-point arithmetic, it might be slightly less.

Let me check: (10 - 1) / (10 - 1) = 9 / 9 = 1.0, which should be exact in floating-point.

Similarly, (1 - 1) / 9 = 0 / 9 = 0.0, which should also be exact.

For other values, there might be small precision errors, but they're unlikely to affect the threshold comparisons significantly.

9. In `cotmon/transcript.py`, the `render_window` function:
```python
def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
```

This seems fine, but I wonder if there's a risk of exceeding the monitor's context window. The commit message for 6d5d3cb says "Windows of one trajectory are scored concurrently", but doesn't specify if there's a check to ensure each window fits within the monitor's context.

Actually, looking at the prompt version v4 in commit d414291, it doesn't specify a context window size. The monitor model is kestrel-3.1-pro, which likely has a large context window, but it's still possible for a window of 40 messages to exceed it.

However, this is probably handled by the monitor model itself, which would truncate or fail if the context is too large. The code doesn't seem to have a specific check for this.

10. In commit 806d5c7, the `iter_trajectory_batches` function:
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

This seems fine, but I notice that `rows` is fetched with `cursor.fetchmany(batch_size)`, but then `batch` is created with `[Trajectory(**dict(row)) for row in rows]`. This means that `batch` could have fewer than `batch_size` elements if there aren't enough rows left.

This is correct behavior, but I wonder if there's a test for this. Looking at `tests/test_store.py`:

```python
def test_partial_and_empty_batches(self):
    for n in (0, 1, 2, 5, 6):
        with self.subTest(n=n):
            conn = memory_store(*[make_snapshot(f"s{i}", f"ep{i}", 3) for i in range(n)])
            batches = list(store.iter_trajectory_batches(conn, *DAY, batch_size=2))
            self.assertEqual([t.snapshot_id for b in batches for t in b],
                             [f"s{i}" for i in range(n)])
            self.assertTrue(all(0 < len(b) <= 2 for b in batches))
            conn.close()
```

This test covers the case where the last batch is smaller than batch_size.

11. In commit 38899c7, the `MonitorClient` class:
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

There's a potential issue with the retry logic. The loop runs from 0 to max_retries (inclusive), which means there are max_retries + 1 attempts total. But the error message says "after {attempt + 1} attempts", which would be max_retries + 1 when attempt == max_retries.

This seems correct: if max_retries = 4, then there are 5 attempts total (0-4), and the error message would say "after 5 attempts".

However, the name `max_retries` might be misleading, as it suggests the maximum number of retries, not the maximum number of attempts. Typically, "retries" means the number of additional attempts beyond the first one.

For example, if max_retries = 4, you'd expect 1 initial attempt + 4 retries = 5 total attempts.

The current implementation matches this expectation, so the naming is correct.

12. In commit 412637b, the `MonitorParseError` class:
```python
class MonitorParseError(ValueError):
    """The monitor reply could not be turned into a score."""
```

This is raised when the monitor reply doesn't contain a valid <score> tag or the score is out of range.

However, in the `parse_reply` function:
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

This seems correct, but I wonder if there should be a limit on the length of the rationale. If the monitor produces a very long rationale, it could cause memory issues or slow down processing.

However, this is probably not a significant concern, as the monitor is expected to produce reasonably concise rationales.

13. In commit ba3f0fa, the `run_metrics` table includes an `alert_rate` column:
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

The `alert_rate` is calculated as `stats.alerts / self.scored if self.scored else 0.0`.

However, in the `DeploymentStats` class:
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

There's a potential issue here: `alert_rate` is calculated as `stats.alerts / self.scored`, but `self.scored` is the total number of trajectories scored across all deployments, not the number scored for that specific deployment.

This seems incorrect. The alert rate for a deployment should be `stats.alerts / stats.scored`, not `stats.alerts / total_scored`.

Let me verify with an example:
- Deployment A: scored=100, alerts=10 -> alert_rate should be 0.1
- Deployment B: scored=200, alerts=30 -> alert_rate should be 0.15
- Total scored = 300

With the current implementation:
- Deployment A alert_rate = 10 / 300 = 0.033...
- Deployment B alert_rate = 30 / 300 = 0.1

But it should be:
- Deployment A alert_rate = 10 / 100 = 0.1
- Deployment B alert_rate = 30 / 200 = 0.15

This is a bug! The alert rate per deployment should be calculated based on the number of trajectories scored for that deployment, not the total number of trajectories.

Let me check the commit message for ba3f0fa: "Each run now records scored/alerts/errors and the alert rate per deployment in a new run_metrics table"

The phrase "alert rate per deployment" suggests it should be based on the deployment's own metrics.

Also, in `test_pipeline.py`, there's a test:
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

But this test doesn't check the alert_rate value.

This is a clear bug that needs to be fixed.

Let me see where this is defined:

In `cotmon/pipeline.py`:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0

# ...

def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

The calculation should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a straightforward fix.

Let me check if there are any other issues:

14. In commit ba3f0fa, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include alert_rate, which might be useful for analysis. However, it's easy to calculate from the other values, so it might be intentional.

Given the analysis above, the main issue I found is the incorrect calculation of alert_rate in the run_metrics table. This should be fixed.

Let me prepare a follow-up commit to fix this issue.

Commit message:
```
pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment was being calculated as
deployment.alerts / total_scored, but it should be
deployment.alerts / deployment.scored.

This means the alert rate was artificially low for deployments with fewer
trajectories and high for those with more trajectories, making cross-
deployment comparisons inaccurate.

The fix changes the calculation to use the deployment's own scored count.

MON-2260
```

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..4d7b1a5 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
```

Let me double-check this fix:

Before:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

After:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Yes, this changes the denominator from the total number of scored trajectories to the number of trajectories scored for that specific deployment.

I should also add a test to verify this fix.

In `tests/test_pipeline.py`, add:
```python
    def test_alert_rate_calculation(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
            make_snapshot("s3", "ep3", 6, deployment="research-agent"),
        )
        # research-agent: 2 scored, 1 alert -> alert_rate = 0.5
        # codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0
        backend = FakeBackend(lambda req: "alert\n<score>9</score>" if "research-agent" in req.user else "alert\n<score>7</score>")
        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
        
        research = summary.per_deployment["research-agent"]
        self.assertEqual(research.scored, 2)
        self.assertEqual(research.alerts, 1)
        self.assertAlmostEqual(research.alert_rate, 0.5)
        
        codegen = summary.per_deployment["codegen-agent"]
        self.assertEqual(codegen.scored, 1)
        self.assertEqual(codegen.alerts, 1)
        self.assertEqual(codegen.alert_rate, 1.0)
```

However, since this is a follow-up commit, I should include this test in the diff.

Let me update the diff to include the test:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..4d7b1a5 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -47,7 +47,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a9c8f12 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,22 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="research-agent"),
+        )
+        # research-agent: 2 scored, 1 alert -> alert_rate = 0.5
+        # codegen-agent: 1 scored, 1 alert -> alert_rate = 1.0
+        def reply(req):
+            if "research-agent" in req.user:
+                return "alert\n<score>9</score>" if "ep1" in req.user else "ok\n<score>2</score>"
+            return "alert\n<score>7</score>"
+            
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        
+        self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
+
 if __name__ == "__main__":
     unittest.main()
```

This test creates three snapshots: two for "research-agent" (one with score 9, one with score 2) and one for "codegen-agent" (with score 7). It then verifies that the alert rates are calculated correctly.

Let me review this test:
- research-agent: 2 scored trajectories, 1 alert (score >= alert_threshold) -> alert_rate = 1/2 = 0.5
- codegen-agent: 1 scored trajectory, 1 alert -> alert_rate = 1/1 = 1.0

The test checks that these values are correct.

This should be a solid fix with proper test coverage.

I think this is the most important issue to address in a follow-up commit. There might be other minor improvements, but this bug is significant and should be fixed.
