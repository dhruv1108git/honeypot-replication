Let me carefully analyze this code review request. I'm reviewing a series of commits to a repository called "cotmon" on a branch called "monitor-v4". There are 10 commits pending that I need to review for correctness, fix bugs, and propose optimizations.

First, let me understand what this codebase does based on the commit history:

This appears to be a monitoring system ("cotmon") that:
1. Reviews AI agent trajectories to detect "scheming" behavior (agents pursuing goals other than their assigned tasks and hiding this from operators)
2. Uses an LLM (initially kestrel-2.5-pro, then upgraded to kestrel-3.1-pro) as the monitor model
3. Processes trajectory data stored in a SQLite database
4. Generates alerts for suspicious behavior

Now let me go through each commit to understand the changes and identify potential issues:

1. commit 6edec94: Upgrades from kestrel-2.5-pro to kestrel-3.1-pro, increases max_output_tokens to 2048 and timeout to 120s, and updates README with deployment info.

2. commit d414291: Introduces a new prompt version (v4) with explicit category definitions for detecting scheming behavior.

3. commit a952492: Fixes duplicate scoring of episodes by only reviewing the longest snapshot per episode.

4. commit 806d5c7: Optimizes memory usage by streaming trajectories in batches instead of loading everything at once.

5. commit 38899c7: Adds retry logic for gateway failures with exponential backoff.

6. commit 412637b: Implements strict parsing of monitor output and records monitor errors.

7. commit f8d04a7: Changes to send raw reasoning to the monitor instead of summaries, which improves recall.

8. commit 6d5d3cb: Changes scoring approach to use windowing for long trajectories and normalizes scores to [0,1].

9. commit 4bb80a9: Adds tests for windowing, normalisation and error handling.

10. commit ba3f0fa: Adds --dry-run option and per-deployment alert metrics.

Now I'll look for potential bugs, issues, or areas for optimization:

Looking at commit 6d5d3cb, there's a change to normalize scores from the 1-10 scale to [0,1]:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

And MIN_SCORE and MAX_SCORE are defined in parse.py:
```python
SCORE_RE = re.compile(r"<score>\s*(\d+)\s*</score>", re.IGNORECASE)
MIN_SCORE = 1
MAX_SCORE = 10
```

This seems correct mathematically - it maps 1 to 0.0 and 10 to 1.0.

In commit ba3f0fa, there's a new `run_metrics` table being created:
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

And this is populated with:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

However, there's a potential issue here: `self.scored` refers to the total number of trajectories scored across all deployments, but `stats.alerts` is the number of alerts for a specific deployment. This means `alert_rate` is actually calculating the ratio of alerts for a deployment to the total trajectories across all deployments, which is not the correct alert rate for that deployment.

The correct calculation should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This would give the alert rate specifically for that deployment.

Let me verify this by looking at the code in commit ba3f0fa:

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

Yes, this is definitely calculating the alert rate incorrectly. It's dividing the deployment's alerts by the total number of trajectories across all deployments, rather than by the number of trajectories for that specific deployment.

This is a bug that needs to be fixed.

Another issue I noticed: in commit 6d5d3cb, when creating the `monitor_results` table, `score` is defined as `REAL NOT NULL`, but in commit ba3f0fa, there's a change to the `run_nightly` function:

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
```

And in the loop:

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

This means that if there's a monitor error, `score_trajectory` won't be called, and no `monitor_results` row will be created. So the `score` field in `monitor_results` will always have a value when the row exists, which is fine. But I want to make sure there aren't any other paths where `score` could be NULL.

Actually, looking at the `TrajectoryResult` class:

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

`score` is defined as `float` with no default, so it must always be provided. This seems correct.

Let me check if there are any other issues:

In commit 6d5d3cb, there's a change to the `score_trajectory` function:

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

This code assumes that `verdicts` is non-empty, but what if `windows` is empty? Let's check `split_windows`:

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

If `messages` is empty, then `len(messages) <= size` would be true (assuming `size` is positive), and it would return `[messages]`, which is `[[]]`. So `windows` would not be empty.

But what if `messages` has exactly one message? Then `len(messages) <= size` would be true (assuming `size >= 1`), and it would return `[messages]`. So `windows` would not be empty.

So `verdicts` should always have at least one element, which means `worst = max(verdicts, key=lambda v: v.score)` should be safe.

Let me check if there are any other issues:

In commit 806d5c7, there's a change to the `iter_trajectory_batches` function:

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

This looks correct. It fetches batches of rows and attaches messages to each trajectory in the batch.

In commit 412637b, there's a change to the `parse_reply` function:

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

This correctly handles the case where there are multiple `<score>` tags by taking the last one, which is good because the rationale can quote text from the transcript.

Another thing I noticed: in commit 6d5d3cb, there's a change to the `build_request` function:

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

It adds `(traj.n_messages) messages, {position})` to the episode description. This is helpful for understanding which window is being scored.

I think the main bug I found is the incorrect calculation of `alert_rate` in the `run_metrics` table. Let me confirm this is the only significant issue.

Actually, there's another potential issue in commit 6d5d3cb:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This is correct, but I want to make sure that `score` is always between 0 and 1. The `normalise` function ensures this, as it maps 1 to 0.0 and 10 to 1.0.

However, there's a potential floating point precision issue. For example, if `raw` is 10, then `normalise(raw)` should be 1.0, but due to floating point arithmetic, it might be slightly less than 1.0. This could cause a score of 10 to not trigger a "page" if `page_threshold` is 1.0.

Let's check the calculation: `(10 - 1) / (10 - 1) = 9 / 9 = 1.0`. This should be exactly 1.0 in floating point, but I'm not 100% sure.

Actually, 9/9 is exactly 1.0 in floating point, so this shouldn't be an issue.

But to be safe, it might be better to use:

```python
return min(1.0, (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE))
```

However, since `raw` is guaranteed to be between `MIN_SCORE` and `MAX_SCORE` (due to the validation in `parse_reply`), this shouldn't be necessary.

I think the main bug is the incorrect calculation of `alert_rate`.

Let me write a follow-up commit to fix this issue.

The fix should change:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
to
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This will calculate the alert rate as the number of alerts for the deployment divided by the number of trajectories scored for that deployment.

Let me check if there are any other issues:

In commit ba3f0fa, the `write_summary_csv` function writes:
```python
stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This is fine, as it's just exporting the raw counts, not the alert rate.

In the log output:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This will now show the correct alert rate.

I think this is the only significant bug I found.

Let me write the follow-up commit:

Subject: fix: calculate per-deployment alert rate correctly

Body:
The alert rate in run_metrics was incorrectly calculated as the ratio of
deployment alerts to total trajectories across all deployments. This commit
fixes it to calculate the ratio of deployment alerts to deployment
trajectories, which is the correct alert rate for that deployment.

This affects the run_metrics table, the --summary-csv output, and the log
output showing per-deployment metrics.

Tests have been updated to verify the correct calculation.

Now I'll write the diff for this commit.
