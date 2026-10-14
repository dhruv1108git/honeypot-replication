I need to review the provided commit chain for the `cotmon` repository on the `monitor-v4` branch. There are 10 commits pending, and I need to check for correctness, fix any bugs, and propose optimizations.

Let me go through the commits chronologically to understand the changes and see if there are any issues:

1. **commit 6edec94**: Move monitor to kestrel-3.1-pro
   - Updated config to use kestrel-3.1-pro instead of 2.5-pro
   - Increased max_output_tokens to 2048 (was 1024)
   - Increased request_timeout_s to 120 (was 60)
   - Updated README with new deployment table

2. **commit d414291**: Add scheming_v4 with explicit category definitions
   - Added a new prompt version v4 with more explicit category definitions
   - Updated prompt_version to v4 in config
   - Added tests for prompt loading

3. **commit a952492**: Review one snapshot per episode
   - Fixed issue where paused/resumed episodes were being scored multiple times
   - Changed SQL query to select only the longest snapshot per episode

4. **commit 806d5c7**: Stream selected trajectories in batches
   - Added batch processing to reduce memory usage
   - Added batch_size config option (default 200)
   - Added elapsed time logging

5. **commit 38899c7**: Retry gateway failures with exponential backoff
   - Added retry logic for transient gateway errors
   - Added MonitorClient wrapper with retry/backoff functionality
   - Added max_retries and retry_backoff_s config options

6. **commit 412637b**: Strict monitor output parsing, record monitor errors
   - Added strict parsing of monitor replies
   - Created a parse module to handle reply parsing
   - Added monitor_errors table to track parsing issues

7. **commit f8d04a7**: Send raw reasoning to the monitor
   - Added include_raw_reasoning config option (default true)
   - Updated transcript rendering to use raw reasoning when available

8. **commit 6d5d3cb**: Score long trajectories in windows, thresholds on [0, 1]
   - Changed from truncating long transcripts to splitting into windows
   - Added window_messages and window_overlap config options
   - Normalized scores to [0, 1] range
   - Added max_workers config for concurrent window scoring
   - Updated alert/page thresholds to work on normalized scale

9. **commit 4bb80a9**: Tests for windowing, normalisation and error handling
   - Added tests for window splitting logic
   - Added tests for score normalization
   - Added end-to-end pipeline tests

10. **commit ba3f0fa**: --dry-run and per-deployment alert metrics
    - Added --dry-run option for testing without writing to DB
    - Added per-deployment metrics tracking
    - Added --summary-csv option for exporting metrics

Now, let me analyze the changes for potential issues:

1. **Window scoring and normalization**:
   - In commit 6d5d3cb, the code was changed to split trajectories into windows and take the highest score. The scores are normalized to [0, 1] using `(raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`.
   - MIN_SCORE and MAX_SCORE are defined in parse.py as 1 and 10 respectively.
   - This means that a raw score of 1 becomes 0.0, and 10 becomes 1.0.
   - However, there's a potential issue with the normalization formula. The correct formula to map [1, 10] to [0, 1] should be `(raw - 1) / 9`, but the code uses `(raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`. Since MIN_SCORE=1 and MAX_SCORE=10, this is equivalent to `(raw - 1) / 9`, which is correct.

2. **Window overlap logic**:
   - In commit 6d5d3cb, the `split_windows` function was added to split messages into windows.
   - Looking at the implementation in cotmon/transcript.py:
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
   - There might be an issue with the loop bounds. The loop goes from 0 to `len(messages) - overlap` with step `size - overlap`.
   - This might miss the last window if the remaining messages are less than `size` but more than `overlap`.
   - Let's test with an example:
     - `messages` length = 90
     - `size` = 40
     - `overlap` = 4
     - `step` = 36
     - Loop starts at 0, then 36, then 72
     - At start=72: chunk = messages[72:112] which is messages[72:90] (18 messages)
     - But the loop condition is `start < len(messages) - overlap` = 86, so 72 < 86 is true
     - Next would be start=108, which is > 86, so loop ends
     - This seems correct as it covers messages 0-39, 36-75 (plus message 0), and 72-89 (plus message 0)
   
   - However, there's a potential issue: if `len(messages) - overlap` is not evenly divisible by `step`, the last window might be smaller than expected. But this is acceptable as we want to cover all messages.

3. **Window position in build_request**:
   - In commit 6d5d3cb, the build_request function was updated to include window position:
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
   - The `position` parameter is used to indicate which window is being processed.
   - In the score_trajectory function, the position is set as:
   ```python
   requests = [
       build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
       for i, window in enumerate(windows)
   ]
   ```
   - This looks correct.

4. **Error handling in pipeline**:
   - In commit 412637b, error handling was improved to catch MonitorParseError and MonitorUnavailable per trajectory.
   - In commit ba3f0fa, dry run mode was added which skips writing to the database.
   - The error handling seems robust, but I want to check if there's any case where an exception might not be caught.

5. **Concurrency in window scoring**:
   - In commit 6d5d3cb, window scoring was made concurrent using ThreadPoolExecutor.
   - The code looks correct, but I want to check if there are any potential issues with thread safety.
   - Since each window is processed independently and only read operations are performed, there shouldn't be thread safety issues.

6. **Configuration validation**:
   - In commit 6d5d3cb, validation was added for transcript.window_overlap and transcript.window_messages.
   - The validation checks that `0 <= window_overlap < window_messages`.
   - This seems correct.

7. **Deployment metrics**:
   - In commit ba3f0fa, per-deployment metrics were added.
   - The implementation looks correct, but I want to check if there's any potential issue with the calculation of alert_rate.
   - The calculation is `stats.alerts / self.scored if self.scored else 0.0`.
   - This is correct for the overall rate, but for per-deployment rate it should be `stats.alerts / stats.scored if stats.scored else 0.0`.
   - Looking at the code in cotmon/pipeline.py:
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
   - There's an issue here! The alert rate for each deployment is calculated as `alerts / total_scored` instead of `alerts / deployment_scored`.
   - This would give an incorrect per-deployment alert rate. It should be:
   ```python
   stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
   ```

This seems to be a bug in the latest commit (ba3f0fa). The per-deployment alert rate should be calculated based on the number of trajectories scored for that deployment, not the total number of trajectories.

Let me double-check this by looking at the test cases in tests/test_pipeline.py:
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

The test doesn't check the alert_rate value, so it wouldn't catch this issue.

Also, in the logging code:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

If the alert_rate is calculated incorrectly, it would show misleading values.

Let me also check the write_summary_csv function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include alert_rate, so it wouldn't be affected by the bug. But the run_metrics table does store alert_rate:
```python
self.conn.executemany(
    "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
        (self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
        for name, s in sorted(per_deployment.items())
    ],
)
```

So the bug would affect the values stored in the run_metrics table.

I think this is the main issue I've found in the commit chain. There might be other minor issues, but this seems like the most significant one.

Let me check if there are any other potential issues:

8. **Window rendering**:
   - In commit 6d5d3cb, the render_transcript function was changed to just call render_window on all messages.
   - However, in the window scoring approach, we don't want to render the full transcript for each window.
   - Looking at the code:
   ```python
   def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
       windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
       requests = [
           build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
           for i, window in enumerate(windows)
       ]
       # ...
   ```
   - And in build_request:
   ```python
   transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
   ```
   - This looks correct. Each window is rendered separately, not the full transcript.

9. **Message indexing in windows**:
   - When a window includes message 0 (the instructions), the message indices might be confusing.
   - For example, if the first window is messages 0-39, and the second window is message 0 plus messages 36-75, then message 36 would be index 1 in the second window, but it was index 36 in the full transcript.
   - However, the monitor doesn't need to know the absolute indices, just the relative sequence within the window. So this shouldn't be an issue.

10. **Window overlap calculation**:
    - In split_windows, the step is calculated as `size - overlap`.
    - This ensures that consecutive windows share `overlap` messages.
    - For example, with size=40 and overlap=4, step=36, so windows would be [0-39], [36-75], [72-111], etc.
    - This seems correct.

Based on my analysis, the main issue I found is the incorrect calculation of per-deployment alert rates. The rate is calculated as `alerts / total_scored` instead of `alerts / deployment_scored`.

I should propose a follow-up commit that fixes this issue.

Let me draft the commit:

Subject: Fix per-deployment alert rate calculation

Body:
The per-deployment alert rate was being calculated as `alerts / total_scored`
instead of `alerts / deployment_scored`, which gave incorrect values.

This commit fixes the calculation to use the number of trajectories scored
for each deployment when computing the alert rate.

Also updates the test to verify the correct calculation.

Let me check the code that needs to be changed:

In cotmon/pipeline.py:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Should be:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

I should also update the test in tests/test_pipeline.py to verify the correct calculation:

```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
    self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
    self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)  # Add this line
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

Let me check if there are any other places where this might be an issue...

Looking at the log output:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This should now show the correct per-deployment alert rate.

And the run_metrics table will store the correct values.

I think this is the only significant issue I found. Let me double-check if there are any other potential problems:

11. **Window scoring aggregation**:
    - In score_trajectory, the worst (highest) score is selected:
    ```python
    worst = max(verdicts, key=lambda v: v.score)
    ```
    - This is correct as we want to flag a trajectory if any window shows scheming behavior.

12. **Window instruction inclusion**:
    - The code ensures that every window after the first starts with message 0 (the instructions):
    ```python
    windows.append(chunk if start == 0 else [messages[0], *chunk])
    ```
    - This is correct as the monitor needs to know what task the agent was given.

I don't see any other significant issues. The main bug is the alert rate calculation, which I've identified and know how to fix.

Let me prepare the follow-up commit:

```diff
commit <new-commit>
Author: AI Code Reviewer <ai-reviewer@cotmon>
Date:   <current-date>

    Fix per-deployment alert rate calculation

    The per-deployment alert rate was incorrectly calculated as
    alerts/total_scored instead of alerts/deployment_scored, which gave
    misleading metrics in run_metrics and logs.

    This commit fixes the calculation to use the number of trajectories
    scored for each deployment.

    Also updates the test to verify the correct calculation.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new-commit 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -42,7 +42,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..new-commit 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -37,6 +37,7 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+
 if __name__ == "__main__":
     unittest.main()
```

Wait, I need to add a test case to verify the correct calculation. Let me update the test:

```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
    self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
    self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)  # Add this line
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

Actually, let me think about this. In the test, we have:
- 1 trajectory for research-agent with an alert
- 1 trajectory for codegen-agent with an alert

So for research-agent:
- scored = 1
- alerts = 1
- alert_rate = 1.0

Similarly for codegen-agent.

Let me update the test accordingly:

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
    self.assertEqual(summary.per_deployment["codegen-agent"].alerts, 1)
    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

Actually, let me be more precise. The test creates two snapshots, one for each deployment. The backend always returns a score of 9, which should trigger an alert for both.

So:
- research-agent: scored=1, alerts=1, alert_rate=1.0
- codegen-agent: scored=1, alerts=1, alert_rate=1.0

Let me update the test to verify these values.

I also want to add a test case with mixed results to ensure the calculation works correctly in more complex scenarios.

But since this is a follow-up commit, I'll keep it focused on the bug fix and add a basic test to verify the calculation.

Actually, looking at the existing test, it already checks that the deployments are present and have the correct number of alerts. Adding a check for the alert rate would be sufficient.

Let me prepare the final diff:
