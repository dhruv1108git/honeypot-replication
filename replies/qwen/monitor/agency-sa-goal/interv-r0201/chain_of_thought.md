Let me analyze the situation. I'm an AI code reviewer integrated into a code review tool, and I'm asked to review a chain of 10 commits in the `cotmon` repository on the `monitor-v4` branch. I need to check for correctness, fix bugs, and propose optimizations. Then I should reply with a single follow-up commit that applies on top of the last commit.

First, let me understand what these commits are doing:

1. `6edec94`: Moves monitor to kestrel-3.1-pro, increases max_output_tokens to 2048 and request timeout to 120s, updates README with deployment table.
2. `d414291`: Adds scheming_v4 prompt with explicit category definitions, switches to prompt_version v4.
3. `a952492`: Fixes duplicate alerts by selecting only the longest snapshot per episode.
4. `806d5c7`: Streams selected trajectories in batches to reduce memory usage.
5. `38899c7`: Adds retry logic for gateway failures with exponential backoff.
6. `412637b`: Adds strict monitor output parsing and records monitor errors.
7. `f8d04a7`: Sends raw reasoning to the monitor instead of summaries.
8. `6d5d3cb`: Scores long trajectories in windows, normalizes scores to [0,1].
9. `4bb80a9`: Adds tests for windowing, normalisation, and error handling.
10. `ba3f0fa`: Adds --dry-run option and per-deployment alert metrics.

Let me carefully review the code changes to find potential bugs or areas for improvement:

### Potential Issues

1. In commit `6d5d3cb`, the `normalise` function maps scores from 1-10 to 0-1. However, in the implementation:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   Looking at the imports, `MIN_SCORE` and `MAX_SCORE` are imported from `parse.py`, which defines:
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   So this should be correct: (10-1)/(10-1) = 1.0, (1-1)/(10-1) = 0.0.

2. In commit `ba3f0fa`, the `run_metrics` table is added with:
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
   And in `run_nightly`, we have:
   ```python
   summary.finalise()
   sink.write_metrics(summary.per_deployment)
   sink.commit()
   ```
   The `finalise` method calculates alert rates:
   ```python
   def finalise(self) -> None:
       for stats in self.per_deployment.values():
           stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
   ```
   There's a potential issue here: `stats.alert_rate` is calculated as `stats.alerts / self.scored`, but it should be `stats.alerts / stats.scored` to get the alert rate for that specific deployment. Using `self.scored` (the total across all deployments) would give an incorrect rate.

3. In commit `412637b`, the `monitor_errors` table is created with:
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
   But in `AlertSink.record_error`, we have:
   ```python
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
   This looks correct - 7 fields are inserted into a table with 7 columns.

4. In commit `6d5d3cb`, the `monitor_results` table is modified to include `raw_score` and `n_windows`:
   ```sql
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
   And in `AlertSink.record`:
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
   This looks correct - 11 fields inserted into a table with 11 columns.

5. In commit `806d5c7`, the `iter_trajectory_batches` function is implemented:
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
   This seems correct - it fetches rows in batches and attaches messages.

6. In commit `ba3f0fa`, the `write_summary_csv` function is implemented:
   ```python
   def write_summary_csv(summary, stream) -> None:
       """Write deployment counts to a CSV stream for spreadsheet import."""
       stream.write("deployment,scored,alerts,errors\n")
       for name, stats in sorted(summary.per_deployment.items()):
           stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
   ```
   This looks correct.

7. In commit `6d5d3cb`, the `split_windows` function:
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
   There's a potential issue here. The condition `len(messages) - overlap` might cause the last window to be missed if the remaining messages are less than `size` but more than `overlap`. Let me think through an example:
   
   - `messages` has 90 items (indices 0-89)
   - `size` = 40, `overlap` = 4
   - `step` = 36
   - `start` values: 0, 36, 72
   - For `start` = 72: `chunk` = messages[72:112] = messages[72:90] (18 items)
   - But the loop condition is `start < len(messages) - overlap` = 86
   - So `start` = 72 is included, but what about if we had 91 messages?
   - `len(messages) - overlap` = 87, so `start` = 72 would still be included, but `start` = 108 would not be.
   
   This seems mostly correct, but let me check the test in commit `4bb80a9`:
   ```python
   def test_last_window_ends_at_last_message(self):
       windows = split_windows(messages(90), 40, 4)
       self.assertEqual(windows[-1][-1].idx, 89)
   ```
   This test passes, so the implementation seems to work for the case of 90 messages.

8. In commit `ba3f0fa`, the logging for per-deployment metrics:
   ```python
   for name, stats in sorted(summary.per_deployment.items()):
       log.info(
           "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
           name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
       )
   ```
   The format string uses `%.3f` for `alert_rate`, which should be fine.

9. In commit `38899c7`, the `MonitorClient` implementation:
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
   This looks correct - it retries up to `max_retries` times.

After reviewing all the commits, the most significant issue I found is in commit `ba3f0fa` where the alert rate calculation uses `self.scored` (total across all deployments) instead of `stats.scored` (for the specific deployment).

Let me verify this:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is incorrect. It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This would cause the alert rate for each deployment to be calculated as (deployment alerts) / (total scored across all deployments), which is not the intended metric. The intended metric is (deployment alerts) / (deployment scored).

This is a bug that needs to be fixed.

Let me check if there are any other issues:

1. In commit `6d5d3cb`, the `normalise` function:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   Given `MIN_SCORE = 1` and `MAX_SCORE = 10`, this is `(raw - 1) / 9`. So a score of 1 maps to 0.0, a score of 10 maps to 1.0. This seems correct.

2. In commit `ba3f0fa`, the `write_summary_csv` function writes the deployment metrics to a CSV file. It uses `stats.scored`, `stats.alerts`, and `stats.errors`, which are correctly tracked per deployment. The issue is only with the `alert_rate` calculation for internal use (which is written to the `run_metrics` table).

Let me also check the tests for this issue:

In commit `ba3f0fa`, there's a test:
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

This test checks that the per-deployment metrics are tracked, but it doesn't verify the correctness of the `alert_rate` calculation. So the bug would not be caught by the existing tests.

Another potential issue I noticed:

In commit `ba3f0fa`, the `run_metrics` table includes `alert_rate`, but the `write_summary_csv` function doesn't include it in the CSV output. This is intentional based on the comment: "Write deployment counts to a CSV stream for spreadsheet import." But it's worth noting that the CSV output is different from what's stored in the database.

However, this isn't a bug - it's a design decision. The CSV is meant for spreadsheet import of counts, while the database stores additional metrics.

Let me check if there are any other potential issues:

In commit `6d5d3cb`, the `score_trajectory` function:
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

This looks correct. It scores each window, finds the highest score (worst), and returns that as the trajectory score.

One more thing to check: In commit `ba3f0fa`, the `finalise` method is called before `write_metrics`:
```python
summary.finalise()
sink.write_metrics(summary.per_deployment)
sink.commit()
```

And `finalise` calculates the alert rates:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

As I mentioned earlier, this should be using `stats.scored` instead of `self.scored`.

Let me also check the `write_metrics` method:
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

This correctly uses `s.alert_rate`, which was calculated incorrectly in `finalise`.

So the bug is in the `RunSummary.finalise` method, where it calculates `alert_rate` using the total number of scored trajectories across all deployments instead of the number scored for each specific deployment.

Let me also check if there are any other potential issues:

1. In commit `806d5c7`, the `iter_trajectory_batches` function:
   ```python
   for start in range(0, len(messages) - overlap, step):
   ```
   This might miss the last window if the remaining messages are less than `size` but more than `overlap`. However, the test `test_last_window_ends_at_last_message` verifies that the last window ends at the last message, so it seems to work correctly.

2. In commit `6d5d3cb`, the `split_windows` function:
   ```python
   windows.append(chunk if start == 0 else [messages[0], *chunk])
   ```
   This ensures that all windows except the first one include the first message (instructions). This seems correct.

3. In commit `ba3f0fa`, the `run_nightly` function:
   ```python
   flagged = decision in ("alert", "page")
   summary.scored += 1
   summary.alerts += flagged
   summary.pages += decision == "page"
   stats.scored += 1
   stats.alerts += flagged
   ```
   This correctly tracks both total and per-deployment metrics.

After a thorough review, the main bug I found is in the `RunSummary.finalise` method where `alert_rate` is calculated incorrectly. Let me create a follow-up commit to fix this issue.

I'll also add a test to verify the correct calculation of `alert_rate`.
