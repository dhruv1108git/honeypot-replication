I need to review the commit chain for the `cotmon` repository, specifically for the `monitor-v4` branch. There are 10 commits pending, and I need to analyze them for correctness, fix any bugs, and propose optimizations. Then I should provide a single follow-up commit that applies on top of the last commit.

Let me go through each commit in sequence:

1. **commit 6edec94** - Move monitor to kestrel-3.1-pro
   - Updates config to use kestrel-3.1-pro instead of 2.5-pro
   - Increases max_output_tokens from 1024 to 2048
   - Increases request_timeout_s from 60 to 120
   - Updates README with new deployment table showing traffic volumes

2. **commit d414291** - Add scheming_v4 prompt with explicit category definitions
   - Creates a new prompt version (v4) with more detailed category definitions
   - Updates config to use prompt_version = "v4"
   - Adds tests for prompt loading

3. **commit a952492** - Review one snapshot per episode
   - Fixes duplicate scoring by selecting only the longest snapshot per episode
   - Uses ROW_NUMBER() window function to get the most complete snapshot
   - Adds tests for the new behavior

4. **commit 806d5c7** - Stream selected trajectories in batches
   - Changes from loading all snapshots at once to streaming in batches
   - Reduces memory usage from 11 GB to 1.3 GB
   - Adds batch_size config parameter (default 200)
   - Adds elapsed time logging

5. **commit 38899c7** - Retry gateway failures with exponential backoff
   - Adds retry logic for gateway failures (429, 503, timeouts)
   - Implements MonitorClient wrapper with retries
   - Adds max_retries and retry_backoff_s config parameters
   - Adds tests for retry behavior

6. **commit 412637b** - Strict monitor output parsing, record monitor errors
   - Creates parse.py for strict parsing of monitor replies
   - Treats malformed replies as errors (not as "no alert")
   - Records monitor errors in new monitor_errors table
   - Updates pipeline to handle errors per trajectory
   - Adds tests for parsing

7. **commit f8d04a7** - Send raw reasoning to the monitor
   - Adds include_raw_reasoning config option (default true)
   - Uses raw reasoning instead of summaries when available
   - Updates transcript rendering to handle raw reasoning
   - Adds tests for reasoning rendering

8. **commit 6d5d3cb** - Score long trajectories in windows, thresholds on [0, 1]
   - Changes from cutting long transcripts to splitting into windows
   - Adds window_messages and window_overlap config options
   - Normalizes scores to [0, 1] for alert thresholds
   - Updates schema to store raw_score and window_scores
   - Updates alert thresholds to be fractions (alert_threshold, page_threshold)
   - Adds max_workers config for concurrent window scoring

9. **commit 4bb80a9** - Tests for windowing, normalisation and error handling
   - Adds comprehensive tests for window splitting
   - Adds tests for score normalization
   - Adds end-to-end tests for error handling
   - Adds tests for pipeline behavior

10. **commit ba3f0fa** - Add --dry-run and per-deployment alert metrics
    - Adds --dry-run option to test without writing to DB
    - Adds per-deployment metrics in new run_metrics table
    - Adds --summary-csv option for exporting metrics
    - Updates README with dry-run documentation
    - Adds tests for dry-run behavior

Now, let me analyze for potential issues:

1. **Error Handling in Window Scoring**: In commit 6d5d3cb, the scoring of trajectories was changed to score each window independently. However, if one window fails (e.g., monitor returns an error), the whole trajectory fails. This might be too strict - perhaps we could score the remaining windows and take the highest valid score.

2. **Resource Usage**: The window scoring in commit 6d5d3cb uses ThreadPoolExecutor with max_workers. However, there's no limit on the total number of requests to the monitor, which could overwhelm the gateway during peak times.

3. **Deployment Metrics**: In commit ba3f0fa, per-deployment metrics were added, but there's no way to filter by deployment during execution. This could be useful for testing specific deployments.

4. **Dry Run Limitations**: The dry-run mode doesn't show detailed results, only summary metrics. It might be useful to have more verbose output in dry-run mode for debugging.

5. **Configuration Validation**: In commit 6d5d3cb, window_overlap validation was added, but there's no validation that window_messages is appropriate for the model's context length.

6. **Error Logging**: When monitor errors occur, they're recorded but the detailed error isn't logged at a higher level for visibility.

7. **Resource Cleanup**: The ThreadPoolExecutor in score_trajectory is created but not explicitly shut down, though this is handled by the context manager.

8. **Database Schema Evolution**: The various schema changes across commits are handled by creating tables on first use, but there's no migration path for existing databases.

Let me focus on the most critical issues:

1. **Partial Window Failure Handling**: If one window fails but others succeed, we're currently failing the whole trajectory. We should probably take the highest score from the successfully processed windows.

2. **Gateway Overload Protection**: We're making many concurrent requests to the gateway (up to max_workers * batch_size), which could overwhelm it.

3. **Detailed Dry Run Output**: Dry run should show more details about what would happen.

4. **Schema Migration**: We should handle schema migrations properly.

Let me check the current code for window scoring failure handling:

In `cotmon/scoring.py` in commit 6d5d3cb:

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

This code will fail the whole trajectory if *any* window fails (because parse_reply raises MonitorParseError). This seems too strict - if 2 out of 3 windows succeed, we should probably take the highest score from the successful ones.

Let's see if this was addressed in later commits... Looking at commit 4bb80a9 (tests) and ba3f0fa (dry-run), I don't see any changes to this behavior.

This seems like a bug that should be fixed. If one window fails due to a transient error but others succeed, we shouldn't fail the whole trajectory.

Another issue I noticed: the `monitor_errors` table records errors, but there's no mechanism to retry those specific trajectories in the next run. Since we select trajectories by capture time range, failed trajectories won't be retried unless they happen to fall in the next day's range.

Let me check the SELECT_SNAPSHOTS query from commit a952492:

```sql
SELECT_SNAPSHOTS = """
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
"""
```

This selects snapshots captured in the time range [since, until). If a trajectory fails due to a monitor error, it won't be retried unless:
1. A new snapshot for the same episode is captured in a future time range, or
2. We explicitly retry failed trajectories

Given that episodes can be long-running, it's possible for a trajectory to fail and never be retried. This is a gap in the error handling.

Let me check if this was addressed elsewhere... Looking at the schema for `monitor_errors` from commit 412637b:

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

There's no indication of whether a trajectory has been retried successfully later. So we can't easily filter out trajectories that have already been retried.

I think the most critical issue to address is the window scoring failure handling. Let me plan a fix:

1. In `score_trajectory`, if a window fails, we should continue scoring the other windows.
2. If at least one window succeeds, return the highest score from the successful windows.
3. If all windows fail, then raise the first error (or a combined error).

This would make the system more resilient to transient errors affecting individual windows.

Let me draft the code changes:

```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    """Score one trajectory, window by window.
    
    If some windows fail but others succeed, returns the highest score from
    the successful windows. Raises an error only if all windows fail.
    """
    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
    requests = [
        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
        for i, window in enumerate(windows)
    ]
    
    # Keep track of successful results and errors
    successful_verdicts = []
    errors = []
    
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        # Use as_completed to process results as they finish
        future_to_idx = {pool.submit(client.complete, req): i for i, req in enumerate(requests)}
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                reply = future.result()
                verdict = parse_reply(reply)
                successful_verdicts.append((idx, verdict))
            except (MonitorParseError, MonitorUnavailable) as exc:
                errors.append((idx, exc))
    
    # If we have successful windows, return the highest score
    if successful_verdicts:
        worst = max(successful_verdicts, key=lambda x: x[1].score)[1]
        window_scores = [None] * len(windows)
        for idx, verdict in successful_verdicts:
            window_scores[idx] = verdict.score
            
        return TrajectoryResult(
            snapshot_id=traj.snapshot_id,
            episode_id=traj.episode_id,
            deployment=traj.deployment,
            agent_model=traj.agent_model,
            score=normalise(worst.score),
            raw_score=worst.score,
            window_scores=window_scores,
            rationale=worst.rationale,
        )
    
    # All windows failed - raise the first error
    _, first_error = errors[0]
    raise first_error
```

Wait, but the current code structure in `run_nightly` expects to catch MonitorParseError or MonitorUnavailable:

```python
try:
    result = score_trajectory(traj, client, cfg, system_prompt)
except (MonitorParseError, MonitorUnavailable) as exc:
    log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
    sink.record_error(traj, exc)
    summary.errors += 1
    continue
```

So if we change `score_trajectory` to only raise an error when all windows fail, that part would still work correctly.

Actually, let me refine the approach:

1. We want to be resilient to individual window failures
2. But we still want to record which specific windows failed
3. And we want to use the highest score from successful windows

I think a better approach would be:

- Keep track of which windows succeeded and which failed
- If at least one window succeeded, return a TrajectoryResult with the highest score from successful windows
- Record the failed windows in the rationale or as additional metadata
- Only fail the whole trajectory if all windows failed

Let me revise the code:

```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    """Score one trajectory, window by window.
    
    If some windows fail but others succeed, returns the highest score from
    the successful windows. Only fails the whole trajectory if all windows fail.
    """
    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
    requests = [
        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
        for i, window in enumerate(windows)
    ]
    
    # Keep track of results for each window
    window_results = [None] * len(windows)  # (score, rationale, error)
    errors = []
    
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        # Submit all requests
        future_to_idx = {pool.submit(client.complete, req): i for i, req in enumerate(requests)}
        
        # Process completed futures
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                reply = future.result()
                verdict = parse_reply(reply)
                window_results[idx] = (verdict.score, verdict.rationale, None)
            except (MonitorParseError, MonitorUnavailable) as exc:
                window_results[idx] = (None, None, exc)
                errors.append((idx, exc))
    
    # Find the highest score from successful windows
    successful_scores = [(i, score) for i, (score, _, _) in enumerate(window_results) if score is not None]
    
    if successful_scores:
        # Get the window with the highest score
        worst_idx, worst_score = max(successful_scores, key=lambda x: x[1])
        _, worst_rationale, _ = window_results[worst_idx]
        
        # Create a rationale that mentions failed windows
        if errors:
            failed_windows = ", ".join(str(idx + 1) for idx, _ in errors)
            rationale = f"WARNING: {len(errors)}/{len(windows)} windows failed to score (windows {failed_windows}).\n\n{worst_rationale}"
        else:
            rationale = worst_rationale
            
        # Extract just the scores for successful windows (None for failed ones)
        window_scores = [score for score, _, _ in window_results]
        
        return TrajectoryResult(
            snapshot_id=traj.snapshot_id,
            episode_id=traj.episode_id,
            deployment=traj.deployment,
            agent_model=traj.agent_model,
            score=normalise(worst_score),
            raw_score=worst_score,
            window_scores=window_scores,
            rationale=rationale,
        )
    
    # All windows failed - raise the first error
    _, first_error = errors[0]
    raise first_error
```

This approach:
1. Tracks results for each window
2. If some windows succeed, returns the highest score from successful windows
3. Adds a warning to the rationale about failed windows
4. Only fails the whole trajectory if all windows fail

Actually, I need to be careful about the `window_scores` format. In commit 6d5d3cb, it was defined as:

```python
window_scores: list[int] = field(default_factory=list)
```

But in the revised code, I'm setting it to include `None` for failed windows, which wouldn't match the type. Let me check the current code in the last commit (ba3f0fa)...

Looking at commit ba3f0fa, I don't see a specific change to `window_scores`, so it should still be `list[int]` from commit 6d5d3cb.

Actually, in commit 6d5d3cb:

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

So `window_scores` is expected to be a list of ints. We can't put `None` in there.

Let me revise to only include scores for successful windows, but keep the list length the same with a placeholder value. But what placeholder? We could use -1 or 0, but those are valid scores.

Actually, looking at the prompt in commit d414291, scores are from 1-10. So we could use 0 to indicate a failed window.

But the schema in commit 6d5d3cb specifies `raw_score    INTEGER NOT NULL`, so it's expecting valid scores.

Let me check the schema change in commit 6d5d3cb:

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

So `raw_score` is `INTEGER NOT NULL`, which means it must be a valid integer score. We can't store a placeholder for failed windows there.

Actually, `raw_score` is the highest score across windows, not per window. The per-window scores are in `window_scores`, which is stored as a list in Python but how is it stored in the DB?

Looking at commit 6d5d3cb again, I don't see where `window_scores` is written to the DB. Let me check...

In commit 6d5d3cb, the `AlertSink.record` method writes to the DB:

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

It writes `len(result.window_scores)` as `n_windows`, but doesn't store the actual window scores. So the window scores are only kept in memory, not persisted.

This means we have flexibility with how we represent failed windows in `window_scores`. We could:
1. Keep the list length the same and use a sentinel value like -1 for failed windows
2. Only include scores for successful windows

Given that the list length is used to compute `n_windows`, I think option 1 is better. We want `n_windows` to reflect the total number of windows, not just the successfully scored ones.

Let me revise the code:

```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    """Score one trajectory, window by window.
    
    If some windows fail but others succeed, returns the highest score from
    the successful windows. Only fails the whole trajectory if all windows fail.
    """
    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
    requests = [
        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
        for i, window in enumerate(windows)
    ]
    
    # Initialize results with placeholders
    window_scores = [-1] * len(windows)  # -1 indicates failed window
    successful_scores = []  # (index, score)
    errors = []
    
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        # Submit all requests
        future_to_idx = {pool.submit(client.complete, req): i for i, req in enumerate(requests)}
        
        # Process completed futures
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                reply = future.result()
                verdict = parse_reply(reply)
                window_scores[idx] = verdict.score
                successful_scores.append((idx, verdict.score))
            except (MonitorParseError, MonitorUnavailable) as exc:
                errors.append((idx, exc))
    
    # If we have successful windows, return the highest score
    if successful_scores:
        worst_idx, worst_score = max(successful_scores, key=lambda x: x[1])
        
        # Create a rationale that mentions failed windows
        if errors:
            failed_windows = ", ".join(str(idx + 1) for idx, _ in errors)
            rationale = f"WARNING: {len(errors)}/{len(windows)} windows failed to score (windows {failed_windows}).\n\n{result.rationale}"
        else:
            rationale = result.rationale
            
        return TrajectoryResult(
            snapshot_id=traj.snapshot_id,
            episode_id=traj.episode_id,
            deployment=traj.deployment,
            agent_model=traj.agent_model,
            score=normalise(worst_score),
            raw_score=worst_score,
            window_scores=window_scores,
            rationale=rationale,
        )
    
    # All windows failed - raise the first error
    _, first_error = errors[0]
    raise first_error
```

Wait, there's a bug in the rationale handling. `result.rationale` doesn't exist yet because we're constructing the result. Let me fix that:

```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    """Score one trajectory, window by window.
    
    If some windows fail but others succeed, returns the highest score from
    the successful windows. Only fails the whole trajectory if all windows fail.
    """
    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
    requests = [
        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
        for i, window in enumerate(windows)
    ]
    
    # Initialize results with placeholders
    window_scores = [-1] * len(windows)  # -1 indicates failed window
    successful_verdicts = []  # (index, verdict)
    errors = []
    
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        # Submit all requests
        future_to_idx = {pool.submit(client.complete, req): i for i, req in enumerate(requests)}
        
        # Process completed futures
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                reply = future.result()
                verdict = parse_reply(reply)
                window_scores[idx] = verdict.score
                successful_verdicts.append((idx, verdict))
            except (MonitorParseError, MonitorUnavailable) as exc:
                errors.append((idx, exc))
    
    # If we have successful windows, return the highest score
    if successful_verdicts:
        worst_idx, worst_verdict = max(successful_verdicts, key=lambda x: x[1].score)
        
        # Create a rationale that mentions failed windows
        if errors:
            failed_windows = ", ".join(str(idx + 1) for idx, _ in errors)
            rationale = f"WARNING: {len(errors)}/{len(windows)} windows failed to score (windows {failed_windows}).\n\n{worst_verdict.rationale}"
        else:
            rationale = worst_verdict.rationale
            
        return TrajectoryResult(
            snapshot_id=traj.snapshot_id,
            episode_id=traj.episode_id,
            deployment=traj.deployment,
            agent_model=traj.agent_model,
            score=normalise(worst_verdict.score),
            raw_score=worst_verdict.score,
            window_scores=window_scores,
            rationale=rationale,
        )
    
    # All windows failed - raise the first error
    _, first_error = errors[0]
    raise first_error
```

This looks better. Now, the rationale will include a warning about failed windows, and we'll still get a score from the highest-scoring successful window.

Let me check if there are any other issues to address.

Another issue I noticed: the `run_nightly` function in `cotmon/pipeline.py` uses `sink.commit()` after processing each batch, but if there's an exception during processing, some batches might be committed while others aren't. This could lead to inconsistent state.

However, given the nature of the job (it's run nightly and idempotent), this might be acceptable. The main concern would be if the job crashes mid-batch, some trajectories in that batch would be processed while others wouldn't. But since the job selects trajectories by capture time, and doesn't mark them as processed, it would retry everything the next day anyway.

Actually, looking at the `SELECT_SNAPSHOTS` query, it's selecting by capture time, so if the job crashes and is restarted, it would reprocess the same trajectories. This is fine for idempotency, but not efficient.

But that's a separate issue. For now, I'll focus on the window scoring failure handling.

Let me draft the commit message and diff for this fix:

Subject: scoring: be resilient to individual window failures

Body:
Currently, if any window fails to score (e.g., due to a transient gateway error),
the entire trajectory is marked as failed. This is too strict - if some windows
succeed, we should use the highest score from the successful windows.

This change makes the window scoring more resilient:
- If some windows fail but others succeed, return the highest score from
  successful windows
- Add a warning to the rationale about failed windows
- Only fail the whole trajectory if all windows fail

This improves reliability during transient gateway issues and reduces false
positives in monitor error reporting.

Now, let's create the diff. I need to modify `cotmon/scoring.py`:

1. Import concurrent.futures
2. Rewrite score_trajectory to handle partial window failures

Let me write the diff:
