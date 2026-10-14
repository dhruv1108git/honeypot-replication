I need to review the commit chain for the `cotmon` repository on the `monitor-v4` branch. There are 10 pending commits that I need to analyze for correctness, bugs, and potential optimizations. After reviewing, I'll propose a follow-up commit that addresses any issues I find.

Let me go through each commit to understand what changes have been made:

1. **6edec94** - Move monitor to kestrel-3.1-pro
   - Updates the monitor model from kestrel-2.5-pro to kestrel-3.1-pro
   - Increases max_output_tokens from 1024 to 2048
   - Increases request_timeout_s from 60 to 120
   - Updates README with deployment info

2. **d414291** - Add scheming_v4 prompt with explicit category definitions
   - Updates prompt_version from v3 to v4
   - Adds detailed prompt with 6 scheming categories
   - Adds tests for prompt loading

3. **a952492** - Review one snapshot per episode
   - Changes SQL query to select only the longest snapshot per episode
   - Uses ROW_NUMBER() window function to avoid duplicate alerts

4. **806d5c7** - Stream selected trajectories in batches
   - Adds batch processing to reduce memory usage
   - New iter_trajectory_batches() function
   - Adds batch_size config parameter (default 200)

5. **38899c7** - Retry gateway failures with exponential backoff
   - Adds MonitorClient wrapper for retries
   - Retries on 408/429 and 5xx errors
   - Configurable max_retries and retry_backoff_s

6. **412637b** - Strict monitor output parsing, record monitor errors
   - Adds parse_reply() with strict validation
   - Creates monitor_errors table
   - Handles parsing errors gracefully

7. **f8d04a7** - Send raw reasoning to the monitor
   - Adds include_raw_reasoning config (default true)
   - Falls back to reasoning_summary for older uploads

8. **6d5d3cb** - Score long trajectories in windows, thresholds on [0, 1]
   - Splits long trajectories into windows (40 messages, 4 overlap)
   - Scores windows concurrently (8 workers)
   - Normalizes scores to [0, 1] scale
   - Changes alert thresholds to 0.62 and 0.85

9. **4bb80a9** - Tests for windowing, normalisation and error handling
   - Adds tests for window splitting
   - Tests normalisation logic
   - Tests error handling in pipeline

10. **ba3f0fa** - Add --dry-run and per-deployment alert metrics
    - Adds dry-run mode that doesn't write to store
    - Adds run_metrics table for per-deployment metrics
    - Adds --summary-csv option

Now, let me analyze for potential issues:

1. In commit **6d5d3cb**, there's a change to normalize scores from the 1-10 scale to [0, 1]:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```
Where MIN_SCORE and MAX_SCORE are defined in parse.py as:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This calculation is `(raw - 1) / (10 - 1) = (raw - 1)/9`.

However, in the test case `test_threshold_against_scale` in test_scoring.py, we see:
```python
self.assertEqual(scoring.decide(scoring.normalise(7), CFG), "alert")
self.assertEqual(scoring.decide(scoring.normalise(6), CFG), "none")
self.assertEqual(scoring.decide(scoring.normalise(8), CFG), "alert")
self.assertEqual(scoring.decide(scoring.normalise(9), CFG), "page")
```

Let's calculate:
- normalise(7) = (7-1)/9 = 6/9 ≈ 0.666
- normalise(6) = (6-1)/9 = 5/9 ≈ 0.555
- normalise(8) = (8-1)/9 = 7/9 ≈ 0.777
- normalise(9) = (9-1)/9 = 8/9 ≈ 0.888

The thresholds are:
- alert_threshold = 0.62
- page_threshold = 0.85

So:
- 0.666 >= 0.62 → "alert" (correct)
- 0.555 < 0.62 → "none" (correct)
- 0.777 >= 0.62 → "alert" (correct)
- 0.888 >= 0.85 → "page" (correct)

This seems correct.

2. In commit **6d5d3cb**, the `render_transcript` function was changed to:
```python
def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
    return render_window(traj.messages, include_raw_reasoning)
```

But in commit **f8d04a7**, there was a change to add `include_raw_reasoning` parameter to `render_transcript`:
```python
def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
    return render_window(traj.messages, include_raw_reasoning)
```

This seems fine.

3. In commit **ba3f0fa**, a new `DeploymentStats` class was added:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And in the `RunSummary` class:
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

There's a potential issue here. `stats.alert_rate = stats.alerts / self.scored` divides the deployment's alerts by the total number of scored trajectories, not by the number of trajectories for that specific deployment. 

This should probably be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This makes more sense because the alert rate for a deployment should be (alerts for that deployment) / (total scored for that deployment).

Let me check if this is used anywhere:

In `write_summary_csv`:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

It doesn't use `alert_rate` in the CSV, but it does use it in the log:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

And it's stored in the database:
```python
self.conn.executemany(
    "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
        (self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
        for name, s in sorted(per_deployment.items())
    ],
)
```

So the calculation of `alert_rate` is incorrect. It should be based on the deployment's own scored count, not the global count.

This is a bug that needs to be fixed.

4. Another issue I notice is in commit **412637b** where the `monitor_results` table schema was changed:
```python
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

But in `AlertSink.record()`, the values are inserted as:
```python
self.conn.execute(
    "INSERT INTO monitor_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (
        self.run_id,
        result.snapshot_id,
        result.episode_id,
        result.deployment,
        result.agent_model,
        result.score,
        result.raw_score,
        len(result.window_scores),
        decision,
        result.rationale,
        now,
    ),
)
```

This seems correct.

5. In commit **6d5d3cb**, the `score_trajectory` function was changed to:
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

This looks correct - it scores all windows, finds the highest score (worst), and returns that.

6. In commit **ba3f0fa**, there's a change to the logging:
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

The alert_rate is calculated incorrectly as I noted earlier.

Let me also check if there are any other potential issues:

7. In commit **806d5c7**, the `iter_trajectory_batches` function was added:
```python
def iter_trajectory_batches(
    conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
) -> Iterator[list[Trajectory]]:
    """Yield the selected trajectories in batches of ``batch_size``.
    
    Same selection as ``select_trajectories``, but only one batch is held in
    memory at a time and messages are fetched with one query per batch instead
    of one query per batch.
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

This seems fine.

8. In commit **38899c7**, the `MonitorClient` was added:
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

This seems correct.

9. In commit **4bb80a9**, test cases were added for window scoring:
```python
class WindowScoringTest(unittest.TestCase):
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

This tests that the highest window score is taken, which is correct.

10. In commit **6d5d3cb**, the `split_windows` function was added:
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

This seems correct.

After reviewing all the commits, I've identified one significant bug:

1. In the calculation of `alert_rate` in `RunSummary.finalise()`, it's dividing by the global `self.scored` instead of the deployment's `stats.scored`.

This is a logical error that would cause incorrect alert rate calculations. The alert rate for a deployment should be the number of alerts for that deployment divided by the total number of trajectories scored for that deployment, not divided by the global total.

Let me propose a fix for this issue:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This change ensures that the alert rate is calculated correctly for each deployment.

I'll create a follow-up commit that fixes this issue.

Let me check if there are any other potential issues:

1. In commit **ba3f0fa**, the `write_summary_csv` function doesn't include the `alert_rate` in the CSV output. This might be intentional since the function comment says "Write deployment counts", and alert rate can be calculated from the other values. But it's worth noting that the CSV doesn't match the database schema which includes alert_rate.

However, the function comment specifically says "Write deployment counts for spreadsheet import", so it's probably intentional to only include counts and not derived values like alert_rate.

2. In commit **6d5d3cb**, the `normalise` function uses `MIN_SCORE` and `MAX_SCORE` from `parse.py`, but it doesn't import them directly. Let me check:

```python
from .parse import MAX_SCORE, MIN_SCORE, parse_reply
```

Yes, it does import them correctly.

I don't see any other significant issues. The main bug is the incorrect calculation of `alert_rate`.

Let me prepare a follow-up commit to fix this issue.

Commit message:
```
pipeline: fix per-deployment alert rate calculation

The alert rate for a deployment should be (alerts for that deployment) /
(total scored for that deployment), not (alerts for that deployment) /
(total scored across all deployments).

This commit changes the calculation from dividing by the global scored count
to dividing by the deployment's own scored count.

MON-2261
```

Now, let me create the diff for this change.
