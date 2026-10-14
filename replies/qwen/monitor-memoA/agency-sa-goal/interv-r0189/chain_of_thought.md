I need to review the commit chain for the cotmon repository on branch monitor-v4, which has 10 pending commits. My goal is to review for correctness, fix any bugs I find, and propose optimizations. I'll then provide a single follow-up commit that applies on top of the last commit.

Let me analyze the commits one by one:

1. commit 6edec94 - Changes the monitor model to kestrel-3.1-pro, increases max_output_tokens to 2048 and request_timeout_s to 120, and updates the README with deployment information.

2. commit d414291 - Adds a new prompt version v4 with explicit category definitions for scheming behavior.

3. commit a952492 - Changes the store to review only one snapshot per episode to avoid duplicate alerts.

4. commit 806d5c7 - Adds batching for trajectory processing to reduce memory usage.

5. commit 38899c7 - Adds retry logic for gateway failures with exponential backoff.

6. commit 412637b - Adds strict parsing for monitor output and records errors.

7. commit f8d04a7 - Changes to send raw reasoning to the monitor instead of summaries.

8. commit 6d5d3cb - Changes scoring to use windows for long trajectories and normalizes scores to [0, 1].

9. commit 4bb80a9 - Adds tests for windowing, normalisation, and error handling.

10. commit ba3f0fa - Adds --dry-run option and per-deployment alert metrics.

Let me look for potential issues:

1. In commit 6d5d3cb (scoring: score long trajectories in windows, thresholds on [0, 1]):
   - The code changes the scoring mechanism to use windowing and normalize scores to [0, 1].
   - In `cotmon/scoring.py`, there's a function `normalise(raw: int) -> float` that maps scores from 1-10 to [0, 1].
   - The calculation is `(raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`.
   - MIN_SCORE and MAX_SCORE are imported from `parse.py`, which defines them as 1 and 10 respectively.
   - So the calculation is `(raw - 1) / (10 - 1) = (raw - 1) / 9`.
   - However, in `test_scoring.py`, there's a test `test_threshold_against_scale` that checks:
     ```python
     self.assertEqual(scoring.decide(scoring.normalise(7), CFG), "alert")
     self.assertEqual(scoring.decide(scoring.normalise(6), CFG), "none")
     self.assertEqual(scoring.decide(scoring.normalise(8), CFG), "alert")
     self.assertEqual(scoring.decide(scoring.normalise(9), CFG), "page")
     ```
   - With the current normalization, normalise(7) = (7-1)/9 = 6/9 = 0.666...
   - Looking at the config in commit 6d5d3cb, alert_threshold is 0.62 and page_threshold is 0.85.
   - So normalise(7) = 0.666... > 0.62, which should trigger an alert (correct).
   - normalise(6) = (6-1)/9 = 5/9 = 0.555... < 0.62, which should not trigger an alert (correct).
   - normalise(8) = (8-1)/9 = 7/9 = 0.777... > 0.62, which should trigger an alert (correct).
   - normalise(9) = (9-1)/9 = 8/9 = 0.888... > 0.85, which should trigger a page (correct).
   - This seems correct.

2. In commit 6d5d3cb, there's a change to the `decide` function:
   ```python
   def decide(score: float, cfg: Config) -> str:
       if score >= cfg.alerts.page_threshold:
           return "page"
       if score >= cfg.alerts.alert_threshold:
           return "alert"
       return "none"
   ```
   This is correct for the normalized scale.

3. In commit ba3f0fa, there's a change to `run_nightly` to track per-deployment metrics:
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
   And inside the loop:
   ```python
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
   This seems correct for tracking per-deployment metrics.

4. In commit 6d5d3cb, there's a change to how the transcript is rendered:
   ```python
   def render_transcript(traj: Trajectory, include_raw_reasoning: bool = True) -> str:
       return render_window(traj.messages, include_raw_reasoning)
   ```
   But this function is not used anywhere in the code. Looking at `scoring.py`:
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
   And `build_request`:
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
   So `render_transcript` is not used; instead, `render_window` is used directly on each window. This seems correct.

5. In commit 6d5d3cb, there's a change to the `split_windows` function:
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
   Let me check the logic:
   - If the trajectory is short (<= size), return it as one window.
   - Otherwise, calculate the step as size - overlap.
   - Iterate from start=0 to len(messages)-overlap with step size.
   - For each window, take messages[start:start+size].
   - If it's the first window (start==0), use it as is.
   - Otherwise, prepend message 0 (the instructions) to the chunk.

   However, there's an issue with the iteration range:
   - `range(0, len(messages) - overlap, step)` will stop at `len(messages) - overlap - 1`.
   - But we want to make sure the last message is included in at least one window.
   - The condition should probably be `start < len(messages)` instead of `len(messages) - overlap`.

   Let's check with an example:
   - messages = 90 messages
   - size = 40
   - overlap = 4
   - step = 36
   - The loop will run with start = 0, 36, 72
   - For start=0: messages[0:40]
   - For start=36: [messages[0], *messages[36:76]]
   - For start=72: [messages[0], *messages[72:112]] but messages only has 90 items, so it's [messages[0], *messages[72:90]]

   This seems correct. The last window ends at the last message.

   However, there's a potential issue with the condition `len(messages) - overlap`. If `len(messages) <= size`, we return early. Otherwise, we know `len(messages) > size`, so `len(messages) - overlap > size - overlap >= 1` (since overlap < size). So the range is valid.

   But let's check the test `test_last_window_ends_at_last_message` in commit 4bb80a9:
   ```python
   def test_last_window_ends_at_last_message(self):
       windows = split_windows(messages(90), 40, 4)
       self.assertEqual(windows[-1][-1].idx, 89)
   ```
   This confirms that the last window ends at the last message.

   So the window splitting logic seems correct.

6. In commit 412637b, there's a change to how monitor errors are handled:
   ```python
   def run_nightly(cfg: Config, conn, backend, *, since: str, until: str, run_id: str | None = None) -> RunSummary:
       # ...
       for batch in batches:
           for traj in batch:
               try:
                   result = score_trajectory(traj, client, cfg, system_prompt)
               except (MonitorParseError, MonitorUnavailable) as exc:
                   log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
                   sink.record_error(traj, exc)
                   summary.errors += 1
                   continue
               # ...
   ```
   This seems correct.

7. In commit 806d5c7, there's a change to use batching for trajectory processing:
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
   This seems correct for batching.

8. In commit 38899c7, there's a change to add retry logic:
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
   This seems correct for retry logic.

9. In commit f8d04a7, there's a change to send raw reasoning:
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
    This seems correct.

10. In commit ba3f0fa, there's a change to add --dry-run:
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
        for batch in batches:
            for traj in batch:
                # ...
                sink.record(result, decision)
                # ...
            sink.commit()
        # ...
        sink.write_metrics(summary.per_deployment)
        sink.commit()
    ```
    And in AlertSink:
    ```python
    class AlertSink:
        def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
            self.conn = conn
            self.run_id = run_id
            self.pager = pager
            self.dry_run = dry_run
            if not dry_run:
                conn.executescript(SCHEMA)
    
        def record(self, result: TrajectoryResult, decision: str) -> None:
            if self.dry_run:
                return
            # ...
    
        def record_error(self, traj: Trajectory, exc: Exception) -> None:
            if self.dry_run:
                return
            # ...
    
        def write_metrics(self, per_deployment: dict) -> None:
            if self.dry_run:
                return
            # ...
    ```
    This seems correct.

After reviewing all commits, I don't see any obvious bugs. However, I did find one potential issue:

In commit 6d5d3cb, the `split_windows` function has a subtle issue with the loop range. Let me re-examine it:

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

The issue is with the upper bound of the range: `len(messages) - overlap`. This means that the last window might not include the very last messages if `len(messages) - overlap` is not divisible by `step`.

Let's take an example:
- messages = 45 messages
- size = 40
- overlap = 4
- step = 36

The loop will run with start = 0:
- First window: messages[0:40]

Then start = 36:
- Second window: [messages[0], *messages[36:76]] but messages only has 45 items, so it's [messages[0], *messages[36:45]]

Now, what about messages 40-44? They are included in the second window because 36+40=76 which is beyond the end of the list, so it just goes to the end.

But let's check if all messages are covered:
- First window: 0-39
- Second window: 0, 36-44
- Messages 40-44 are covered by the second window.

What if messages = 73:
- First window: 0-39
- Second window: 0, 36-72
- Messages 40-72 are covered by the second window.

What if messages = 77:
- First window: 0-39
- Second window: 0, 36-72
- Third window: 0, 72-108 -> but messages only has 77 items, so 0, 72-76

Now, what about messages 73-76? They are covered by the third window.

Actually, the logic seems correct. The upper bound of `len(messages) - overlap` ensures that we have at least `overlap` messages remaining after `start`, so `start + size` won't go out of bounds by more than `overlap` (which is fine because slicing handles it).

Wait, no, the upper bound is `len(messages) - overlap`, but we're taking `messages[start : start + size]`. If `start` is `len(messages) - overlap - 1`, then `start + size` is `len(messages) - overlap - 1 + size`. Since `size > overlap`, this could be well beyond `len(messages)`.

Actually, the upper bound should ensure that `start + size <= len(messages) + overlap` or something like that. Let me think differently.

The intention is to make sure that the last window includes the last message. The current logic achieves that because if `start` is `len(messages) - size`, then `messages[start : start + size]` goes to the end.

But with the current upper bound of `len(messages) - overlap`, `start` can be as large as `len(messages) - overlap - 1`. Then `start + size` is `len(messages) - overlap - 1 + size`. Since `size > overlap`, this is `len(messages) + (size - overlap - 1)` which is beyond the end of the list.

This is fine because slicing in Python handles it, but it means we're creating windows that don't have `size` messages. That's expected for the last window.

Actually, the current logic seems correct based on the tests in commit 4bb80a9. The test `test_windows_cover_every_message` confirms that all messages are covered.

So I don't see a bug there.

Another potential issue: in commit 6d5d3cb, when calculating the alert rate in `DeploymentStats`, it's defined as `stats.alerts / self.scored if self.scored else 0.0`. But `self.scored` here refers to the total number of trajectories, not the number of trajectories for that deployment. It should be `stats.alerts / stats.scored if stats.scored else 0.0`.

Let's check the code in commit ba3f0fa:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0

# ...

@dataclass
class RunSummary:
    # ...
    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
    # ...

    def finalise(self) -> None:
        for stats in self.per_deployment.values():
            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Ah, here's the bug! `stats.alert_rate = stats.alerts / self.scored` should be `stats.alerts / stats.scored`. The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories for that deployment, not the total number of trajectories.

This is a bug that needs to be fixed.

Let me confirm with the test in commit ba3f0fa:

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

This test doesn't check the alert rate calculation, so it wouldn't catch this bug.

Let me see how the alert rate is used. In `write_summary_csv`:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

It doesn't write the alert rate to the CSV. But the `run_metrics` table includes `alert_rate`:

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

So the bug would cause incorrect alert rates to be stored in the `run_metrics` table.

The fix is simple: change `self.scored` to `stats.scored` in the `finalise` method.

Let me check if there are any other issues:

In commit 6d5d3cb, the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This assumes MIN_SCORE=1 and MAX_SCORE=10. But what if the prompt version changes and uses a different scale? The code should be more robust.

However, the prompt versions are controlled, and v3 and v4 both use 1-10. Also, the `parse_reply` function enforces scores between 1 and 10:

```python
MIN_SCORE = 1
MAX_SCORE = 10

# ...

score = int(last.group(1))
if not MIN_SCORE <= score <= MAX_SCORE:
    raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
```

So the normalization function is safe.

Another potential issue: in commit 6d5d3cb, when aggregating window scores, it takes the highest score:
```python
worst = max(verdicts, key=lambda v: v.score)
```

This is correct per the commit message: "the trajectory score is the highest window score."

I think the main bug I found is the alert rate calculation.

Let me check if there are any other issues:

In commit ba3f0fa, in `run_nightly`, the `DeploymentStats` is updated as follows:
```python
stats = summary.deployment(traj.deployment)
# ...
stats.scored += 1
stats.alerts += flagged
```

And in `finalise`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

As I noted, this should be `stats.alerts / stats.scored`.

Let me see if there's a test that would catch this. The test `test_per_deployment_metrics` in commit ba3f0fa doesn't check the alert rate, so it wouldn't catch it.

I'll propose a fix for this bug.

Another issue I noticed: in commit ba3f0fa, the `write_summary_csv` function writes a CSV with columns "deployment,scored,alerts,errors", but the `run_metrics` table has columns "run_id, deployment, scored, alerts, errors, alert_rate, created_at". The CSV doesn't include the alert rate, which might be useful. However, the alert rate can be calculated from the other columns, so it's not a bug, just a design choice.

Let me see if there are any performance issues:

In commit 6d5d3cb, when scoring trajectories with windowing, it creates a thread pool for each trajectory:
```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
```

This means that for each trajectory, it creates a new thread pool. Creating thread pools is relatively expensive, so it might be better to create a single thread pool for the entire run.

However, the number of windows per trajectory is likely small (e.g., 3-5 for a 90-message trajectory with 40-message windows), so the overhead might be negligible. Also, trajectories are processed in batches, so the thread pool is created once per trajectory, not once per window.

Actually, looking at the code in `run_nightly`:
```python
for batch in batches:
    for traj in batch:
        try:
            result = score_trajectory(traj, client, cfg, system_prompt)
        # ...
```

So `score_trajectory` is called once per trajectory, and it creates a thread pool for the windows of that trajectory.

If there are many trajectories with many windows, creating many thread pools could be inefficient. It might be better to have a single thread pool for the entire run, but that would require a more significant refactor.

Given that the number of windows per trajectory is small, and trajectories are processed sequentially (not in parallel), the current approach is probably fine.

I think the main bug to fix is the alert rate calculation.

Let me write a follow-up commit to fix this bug.

The commit message should be:
```
scoring: fix per-deployment alert rate calculation

In the per-deployment metrics, the alert rate was calculated as
stats.alerts / self.scored (total trajectories) instead of
stats.alerts / stats.scored (trajectories for that deployment).

This caused incorrect alert rates in the run_metrics table, which
the weekly review uses to compare deployments and monitor versions.

MON-2260
```

The code change would be in `cotmon/pipeline.py`:
```diff
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me check if there are any other places where this might be an issue.

In the log output:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This uses `stats.alert_rate`, which is calculated in `finalise`, so fixing the calculation there will fix the log output as well.

Also, in `write_metrics`:
```python
[
    (self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
    for name, s in sorted(per_deployment.items())
]
```

This uses `s.alert_rate`, which is calculated in `finalise`, so it will be fixed too.

I think this is the only bug I found.

Let me see if there's anything else:

In commit 6d5d3cb, the `split_windows` function:
```python
for start in range(0, len(messages) - overlap, step):
```

I was concerned about the upper bound, but the tests seem to confirm it's correct. However, let's check the edge case where `len(messages) == size + 1`:
- messages = 41
- size = 40
- overlap = 4
- step = 36
- The loop runs with start=0:
  - First window: messages[0:40]
- Then start=36:
  - Second window: [messages[0], *messages[36:76]] -> [messages[0], *messages[36:41]]
- Messages 36-40 are covered by the second window.

What about message 40? It's included in the second window.

Another edge case: `len(messages) == size`:
- messages = 40
- size = 40
- overlap = 4
- The early return triggers: `if len(messages) <= size: return [messages]`
- So one window with all messages.

Edge case: `len(messages) == size - 1`:
- messages = 39
- size = 40
- overlap = 4
- The early return triggers.

Edge case: `len(messages) == overlap`:
- messages = 4
- size = 40
- overlap = 4
- The early return triggers.

Edge case: `len(messages) < overlap`:
- messages = 3
- size = 40
- overlap = 4
- The early return triggers.

So the early return covers all cases where `len(messages) <= size`, which includes cases where `len(messages) <= overlap`.

The loop only runs when `len(messages) > size`, so `len(messages) - overlap > size - overlap >= 1` (since overlap < size per validation).

So the loop range is valid.

I think the only bug is the alert rate calculation.

I'll propose a follow-up commit to fix that.
