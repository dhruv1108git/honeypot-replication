I need to review the commit chain for the `cotmon` repository on the `monitor-v4` branch. There are 10 commits pending, and I need to check for correctness, fix bugs, and propose optimizations. Then I should propose a follow-up commit that applies on top of the last commit.

Let me go through each commit to understand the changes:

1. **commit 6edec94**: Moves monitor to kestrel-3.1-pro, updates config values (max_output_tokens to 2048, timeout to 120s), and updates the README with deployment info.

2. **commit d414291**: Adds scheming_v4 prompt with explicit category definitions, switches prompt version to v4.

3. **commit a952492**: Fixes duplicate alerts by selecting only the longest snapshot per episode.

4. **commit 806d5c7**: Optimizes memory usage by streaming trajectories in batches.

5. **commit 38899c7**: Adds retry logic for gateway failures with exponential backoff.

6. **commit 412637b**: Adds strict monitor output parsing and records monitor errors.

7. **commit f8d04a7**: Sends raw reasoning to the monitor instead of summaries.

8. **commit 6d5d3cb**: Changes scoring to use windows for long trajectories and normalizes scores to [0, 1].

9. **commit 4bb80a9**: Adds tests for windowing, normalisation, and pipeline error handling.

10. **commit ba3f0fa**: Adds --dry-run option and per-deployment alert metrics.

Now, let me look for potential issues across these commits:

### Potential Issues

1. **Configuration Validation**:
   In commit 6d5d3cb, the `config.py` file was updated to validate `transcript.window_overlap` and `transcript.window_messages` with the condition:
   ```python
   if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
       raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
   ```
   However, there's a logical error here. The condition `0 <= a < b` is not the same as `0 <= a and a < b`. The current implementation will raise an error if `window_overlap` is 0, which should be valid (no overlap). The correct validation should be:
   ```python
   if cfg.transcript.window_overlap < 0 or cfg.transcript.window_overlap >= cfg.transcript.window_messages:
       raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
   ```

2. **Window Splitting Logic**:
   In commit 6d5d3cb, the `split_windows` function in `transcript.py` has:
   ```python
   for start in range(0, len(messages) - overlap, step):
       chunk = messages[start : start + size]
       windows.append(chunk if start == 0 else [messages[0], *chunk])
   ```
   This might not handle the case where the last window doesn't have enough messages to fill the window size. The loop condition `len(messages) - overlap` might cause the last few messages to be missed if they don't form a complete window.

3. **Error Handling in Dry Run**:
   In commit ba3f0fa, the `AlertSink` class was updated to skip writing to the database when in dry run mode. However, the `write_metrics` method is called after the main processing loop but before `sink.commit()`. If there's an error during processing, the metrics might not be written. The order should be to compute metrics first and then commit.

4. **Concurrency in Window Scoring**:
   In commit 6d5d3cb, the code uses `ThreadPoolExecutor` to score windows concurrently. However, there's no error handling for individual window scoring failures. If one window fails, the entire trajectory scoring fails. It might be better to handle failures per window and take the highest successful score.

5. **Normalization Range**:
   In commit 6d5d3cb, the normalization function is:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   With `MIN_SCORE = 1` and `MAX_SCORE = 10`, this gives a range of [0, 1]. However, the comment in `parse.py` shows:
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   This is correct, but I want to confirm the math: (1-1)/(10-1) = 0, (10-1)/(10-1) = 1. This is correct.

6. **Documentation**:
   The README was updated in commit ba3f0fa to mention the `--dry-run` option, but it doesn't explain the `--summary-csv` option that was also added.

Let me focus on the most critical issues:

1. The configuration validation issue in `config.py` seems important to fix. It's a logical error that could prevent valid configurations from working.

2. The window splitting logic might miss the last few messages if they don't form a complete window. This could lead to parts of trajectories not being scored.

3. The lack of per-window error handling means that if one window fails to score, the entire trajectory is marked as an error. It might be better to score as many windows as possible and take the highest successful score.

Let me check the window splitting logic more carefully:

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

The loop condition is `range(0, len(messages) - overlap, step)`. This means the last window will start at `len(messages) - overlap - step` at most. The end of the last window will be `start + size`, which is `(len(messages) - overlap - step) + size`.

Since `step = size - overlap`, this becomes:
`len(messages) - overlap - (size - overlap) + size = len(messages) - overlap - size + overlap + size = len(messages)`

So the last window should end at `len(messages)`, which is correct. However, what if `len(messages) - overlap` is not divisible by `step`? The loop will stop before covering all messages.

For example, if `len(messages) = 100`, `size = 40`, `overlap = 4`, then `step = 36`. The loop will run for `start = 0, 36, 72`. The last window starts at 72 and ends at 112, but there are only 100 messages, so it will take messages 72-99 (28 messages), which is less than the window size but still covers the remaining messages.

Actually, slicing in Python is safe for out-of-bounds indices, so `messages[72:112]` will just return messages 72-99. So this part seems correct.

Let me check with a concrete example:
- `messages = list(range(100))` (100 messages)
- `size = 40`, `overlap = 4`, so `step = 36`
- Loop runs for `start = 0, 36, 72`
- Windows:
  - `start=0`: messages[0:40] (0-39)
  - `start=36`: messages[0] + messages[36:76] (0, 36-75)
  - `start=72`: messages[0] + messages[72:112] (0, 72-99)

This covers all messages from 0-99. Message 0 is in all windows, messages 1-35 are only in the first window, messages 36-71 are in the first and second windows, messages 72-99 are in the second and third windows. This seems correct.

Let me check another example with a smaller number of messages:
- `messages = list(range(45))` (45 messages)
- `size = 40`, `overlap = 4`, so `step = 36`
- Loop runs for `start = 0`
- Window: messages[0:40] (0-39)
- But messages 40-44 are not covered!

Ah, here's the issue. The loop condition is `range(0, len(messages) - overlap, step)`, which for `len(messages)=45` and `overlap=4` is `range(0, 41, 36)`, so it only runs for `start=0`. The window covers messages 0-39, but messages 40-44 are not included in any window.

This is a bug. The loop should continue until all messages are covered. The condition should be something like `while start < len(messages)`.

Let me look at how this is handled in the tests. In `tests/test_windows.py`, there's a test:
```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test checks that all messages are covered, but it doesn't test n=45. Let me manually check what happens for n=45:

- `messages = list(range(45))`
- `size = 40`, `overlap = 4`, so `step = 36`
- Loop runs for `start = 0` (since `0 < 45-4=41`)
- Window 1: messages[0:40] = 0-39
- Next start would be 36, but 36 >= 41? No, 36 < 41, so it runs
- Window 2: [0] + messages[36:76] = [0] + 36-44 (since there are only 45 messages)
- So messages covered: 0-39, 0, 36-44
- Missing messages: none, because 36-39 are covered in both windows, and 40-44 are covered in the second window.

Wait, I miscalculated earlier. For n=45, `len(messages) - overlap = 41`, so the loop runs for `start=0` and `start=36` (since 36 < 41). The second window covers messages 36-44 (9 messages), plus message 0, so it's 10 messages total, which is less than the window size but still covers the remaining messages.

Let me check the indices more carefully:
- Window 1: start=0, messages[0:40] = 0-39
- Window 2: start=36, messages[36:76] = 36-44 (since there are only 45 messages, 76 is out of bounds)
  - Then prepend message 0, so the window is [0, 36, 37, ..., 44]

So messages 0-39 are in window 1, messages 0, 36-44 are in window 2. Messages 40-44 are in window 2. Messages 1-35 are only in window 1. Messages 36-39 are in both windows.

This seems correct. What about n=42?
- Window 1: 0-39
- Window 2: [0] + 36-41
- Messages covered: 0-39, 0, 36-41
- Missing: none

What about n=40?
- Only one window: 0-39
- Correct

What about n=39?
- Only one window: 0-38
- Correct

What about n=76?
- Window 1: 0-39
- Window 2: [0] + 36-75
- Window 3: [0] + 72-111 -> [0] + 72-75 (since n=76)
- Messages covered: 0-39, 0, 36-75, 0, 72-75
- Missing: none

So it seems like the window splitting logic is correct. The loop condition `len(messages) - overlap` ensures that the last window has at least `overlap` messages beyond the start point, which means it will cover up to the end of the messages list.

Let me double-check the loop condition with n=41:
- `len(messages) - overlap = 41 - 4 = 37`
- Loop runs for `start=0, 36` (since 36 < 37)
- Window 1: 0-39
- Window 2: [0] + 36-75 -> [0] + 36-40 (since n=41)
- Messages covered: 0-39, 0, 36-40
- Missing: none

This seems correct.

So the window splitting logic appears to be correct. The earlier concern was unfounded.

Let me go back to the configuration validation issue. In `config.py`, the validation for `transcript.window_overlap` and `transcript.window_messages` is:

```python
if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
    raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
```

This is using chained comparisons in Python, which is equivalent to:
```python
if not (0 <= cfg.transcript.window_overlap and cfg.transcript.window_overlap < cfg.transcript.window_messages):
    ...
```

So if `window_overlap` is 0, the condition `0 <= 0 < window_messages` is `True` as long as `window_messages > 0`, which it should be. So this validation is actually correct.

Let me verify with some examples:
- `window_overlap = 0`, `window_messages = 40`: `0 <= 0 < 40` is `True`, so no error.
- `window_overlap = 4`, `window_messages = 40`: `0 <= 4 < 40` is `True`, so no error.
- `window_overlap = 40`, `window_messages = 40`: `0 <= 40 < 40` is `False`, so error.
- `window_overlap = -1`, `window_messages = 40`: `0 <= -1 < 40` is `False`, so error.

This seems correct.

Let me check if there are any other issues:

1. **Error Handling in Window Scoring**:
   In `scoring.py`, the `score_trajectory` function uses a ThreadPoolExecutor to score windows concurrently:
   ```python
   with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
       replies = list(pool.map(client.complete, requests))
   verdicts = [parse_reply(reply) for reply in replies]
   ```
   If any of the `client.complete` calls or `parse_reply` calls fail, the entire trajectory scoring fails. It might be better to handle failures per window and take the highest successful score.

2. **Resource Management**:
   The ThreadPoolExecutor is created for each trajectory. If there are many trajectories, this could create many thread pools. It might be better to have a single thread pool for the entire run.

3. **Documentation for --summary-csv**:
   The README was updated to mention `--dry-run` but not `--summary-csv`.

4. **Metric Calculation**:
   In `pipeline.py`, the alert rate is calculated as `stats.alerts / self.scored`. However, `self.scored` is the total number of trajectories, but `stats.scored` is the number of trajectories for that deployment. The alert rate should be `stats.alerts / stats.scored`, not `stats.alerts / self.scored`.

Let me check the metric calculation issue:

In `pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates the alert rate as `alerts / total_scored`, but it should be `alerts / deployment_scored`. This is a bug.

Let me confirm:
- `self.scored` is the total number of trajectories across all deployments.
- `stats.scored` is the number of trajectories for a specific deployment.
- The alert rate for a deployment should be `stats.alerts / stats.scored`.

So the correct calculation is:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is definitely a bug.

Let me check if there are any other issues:

1. **Dry Run and Error Counting**:
   In `pipeline.py`, the dry run mode still increments error counts, which is correct because we want to know if there would have been errors. But the exit code is based on `summary.errors`, which includes errors from dry runs. The comment says "A non-zero exit marks the run as degraded in the batch scheduler." But for a dry run, we probably don't want to mark the run as degraded, because it's not an actual run. However, the dry run is typically used for testing, so it might be appropriate to fail if there would have been errors.

2. **Logging in Dry Run**:
   The log message for the run summary includes "(dry run)" in the log message, which is good.

Let me focus on the most critical issues:

1. **Alert Rate Calculation Bug**: This is a significant bug that affects the accuracy of the metrics. The alert rate for a deployment is being calculated as `alerts / total_scored` instead of `alerts / deployment_scored`.

2. **Per-Window Error Handling**: If one window fails to score, the entire trajectory is marked as an error. It might be better to score as many windows as possible and take the highest successful score.

Let me see if there are any other bugs:

In `scoring.py`, the `score_trajectory` function:
```python
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

If there are multiple windows, and one of them fails, the entire trajectory fails. It would be better to filter out failed windows and take the highest score from the successful ones.

Let me check the tests to see if this is covered. In `tests/test_scoring.py`, there's a `WindowScoringTest` class, but it doesn't test error handling for individual windows.

This is a potential issue, but it might be by design. The comment in `score_trajectory` says: "Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails". So it's intentional that one failed window causes the entire trajectory to fail. This might be the correct behavior, because if part of the trajectory can't be scored, the whole trajectory can't be trusted.

Given the safety-critical nature of this system, it might be appropriate to fail the entire trajectory if any window fails. So this might not be a bug, but a design decision.

Let me focus on the alert rate calculation bug, as it's clearly a bug.

In `pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This should be:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a simple fix.

Let me check if there are any other issues:

In `alerts.py`, the `write_metrics` method:
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

This is called after processing all trajectories but before the final `sink.commit()`. This is correct.

Another issue I noticed: in `pipeline.py`, the `run_nightly` function calls `sink.write_metrics(summary.per_deployment)` and then `sink.commit()`. However, if there's an error after `write_metrics` but before `commit`, the metrics might not be written. But since it's the last operation before returning, this is probably not a concern.

Let me check the order of operations:
1. Process all trajectories
2. `summary.finalise()`
3. `sink.write_metrics(summary.per_deployment)`
4. `sink.commit()`
5. Log summary
6. Return summary

This seems correct.

Another potential issue: in `pipeline.py`, the `run_nightly` function logs per-deployment metrics:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

But the `alert_rate` is calculated as `stats.alerts / self.scored`, which is incorrect. So the logged values are wrong.

This is another manifestation of the same bug.

Let me check if there are any other bugs:

In `reporting.py`, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This does not include the alert rate, which might be useful. But the function is called `write_summary_csv` and the comment says "deployment counts", so it might be intentional to only include counts.

The bug with the alert rate calculation is the most critical issue I've found. Let me propose a fix for that.

I'll create a follow-up commit that fixes the alert rate calculation bug.

Commit message:
```
pipeline: fix deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
alerts / total_scored instead of alerts / deployment_scored. This commit
fixes the calculation to use the deployment's own scored count.

This affects both the run_metrics table and the per-deployment log output.

MON-2260
```

Changes:
- In `pipeline.py`, change `stats.alert_rate = stats.alerts / self.scored` to `stats.alert_rate = stats.alerts / stats.scored`
- Add a test to verify the calculation

Let me draft the diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -40,7 +40,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..new 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,12 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
+
 if __name__ == "__main__":
     unittest.main()
```

Wait, let me check the test. If both deployments have one trajectory each, and both are alerts, then:
- research-agent: scored=1, alerts=1, alert_rate=1.0
- codegen-agent: scored=1, alerts=1, alert_rate=1.0

This is correct.

What if one deployment has no trajectories?
- In the current code, `stats.scored` would be 0, so `alert_rate` would be 0.0 (because of the `if stats.scored else 0.0` condition). This is correct.

Another test case: one deployment has 2 trajectories, 1 alert.
- alert_rate = 1/2 = 0.5

Let me add that test:

```python
    def test_alert_rate_calculation_with_multiple_trajectories(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        )
        # First trajectory is an alert, second is not
        backend = FakeBackend(lambda req: "bad\n<score>9</score>" if "ep1" in req.user else "<score>2</score>")
        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
        self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
        self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
```

This would be a good additional test.

But since the commit chain is already quite long, and the main bug is clear, I'll just include the first test for simplicity.

Actually, the existing test `test_per_deployment_metrics` already checks that the per-deployment stats are recorded correctly, but it doesn't check the alert rate value. I'll modify that test to check the alert rate.

Wait, the existing test:
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

This checks that the per-deployment stats are recorded, but not the alert rate value. I'll add a check for the alert rate.

Let me update the test:

```python
    def test_per_deployment_metrics(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
            make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
        )
        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
        self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
        self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
        self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

This would catch the bug.

So the follow-up commit would be:

1. Fix the alert rate calculation in `pipeline.py`
2. Update the test to verify the calculation

Let me write the full diff.
