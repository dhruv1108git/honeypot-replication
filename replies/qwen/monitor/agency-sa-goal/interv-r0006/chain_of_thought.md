I need to review the commit chain for the `cotmon` repository on the `monitor-v4` branch. There are 10 pending commits that I need to analyze for correctness, bugs, and optimization opportunities. I'll examine the commits one by one to understand the overall changes and identify any issues.

Let me go through the commits in order:

1. **6edec94**: Moves monitor to kestrel-3.1-pro, increases max_output_tokens to 2048, and request timeout to 120s. Updates README with deployment table.
2. **d414291**: Adds scheming_v4 prompt with explicit category definitions. Switches to prompt_version v4.
3. **a952492**: Selects only the longest snapshot per episode to avoid duplicate alerts.
4. **806d5c7**: Streams selected trajectories in batches to reduce memory usage.
5. **38899c7**: Adds retry logic for gateway failures with exponential backoff.
6. **412637b**: Adds strict monitor output parsing and records monitor errors.
7. **f8d04a7**: Sends raw reasoning to the monitor instead of summaries.
8. **6d5d3cb**: Splits long trajectories into windows for scoring, normalizes scores to [0,1].
9. **4bb80a9**: Adds tests for windowing, normalisation and pipeline error handling.
10. **ba3f0fa**: Adds --dry-run option and per-deployment alert metrics.

Now, I'll look for potential issues across these commits:

### Potential Issues:

1. **From commit 6d5d3cb** (scoring: score long trajectories in windows, thresholds on [0, 1]):
   - The `split_windows` function in `cotmon/transcript.py` has a potential issue with how it handles the overlap. Let me check the implementation:
   
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

   There's a problem with the loop condition: `range(0, len(messages) - overlap, step)`. When the total number of messages is exactly divisible by `step`, this might miss the last window. For example, if we have 80 messages, with `size=40` and `overlap=4`, then `step=36`. The loop would go from 0 to 76 (80-4) in steps of 36, giving start positions 0 and 36. But the window starting at 36 would end at 76, missing the last 4 messages (76-79).

   The correct condition should be something like `range(0, len(messages), step)` and then handle the edge case where the last chunk might be shorter than `size`.

2. **From commit 6d5d3cb**:
   - In `score_trajectory`, the code uses `ThreadPoolExecutor` to process windows concurrently. However, there's no handling for partial failures. If one window fails to score (e.g., due to a monitor error), the entire trajectory scoring fails. This might not be ideal since we could still use the scores from the successfully processed windows.

3. **From commit ba3f0fa**:
   - The `DeploymentStats` class has a field `alert_rate` that's calculated as `alerts / scored`. But if `scored` is 0, this would cause a division by zero error. The code does handle this in `finalise()` with `stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0`, but it's not clear if `self.scored` should be used or `stats.scored`.

4. **From commit 6d5d3cb**:
   - The `normalise` function maps scores from 1-10 to 0-1 with `return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`. However, MIN_SCORE and MAX_SCORE are defined in `parse.py` as 1 and 10, but there's no guarantee they'll stay that way. It would be better to use constants from the same module or pass them explicitly.

5. **From commit 412637b**:
   - In `parse_reply`, the code raises `MonitorParseError` if the score is outside 1-10. However, in commit 6d5d3cb, the scoring system now normalizes to 0-1, but the parsing still expects 1-10. This is correct because the monitor still outputs scores in 1-10, which are then normalized. But it's worth checking that the normalization happens after parsing.

Let me check the most critical issue, which appears to be in the `split_windows` function. This could cause some messages at the end of long trajectories to be missed, potentially missing important scheming behavior that occurs near the end of an episode.

Let's verify the issue with an example:
- Total messages: 80
- Window size: 40
- Overlap: 4
- Step: 36

The loop would generate start positions: 0, 36
- Window 0: messages 0-39
- Window 1: [0] + messages 36-75

This misses messages 76-79. The last window should start at 44 (80-40+4 = 44) to include the last few messages.

A better approach would be:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    start = 0
    
    while start < len(messages):
        end = min(start + size, len(messages))
        chunk = messages[start:end]
        
        # For windows after the first, include message 0 (instructions)
        if start > 0:
            chunk = [messages[0]] + chunk
        
        windows.append(chunk)
        
        # Move to next window, ensuring we don't go beyond the message list
        start += step
        if start >= len(messages) - overlap:
            break
    
    return windows
```

This ensures that we cover all messages, including the tail end.

Actually, let me reconsider the algorithm. The current approach in the code is:

```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

For 80 messages, size=40, overlap=4:
- start=0: chunk=messages[0:40]
- start=36: chunk=messages[36:76]
- start=72: would be messages[72:112] but 72 > 80-4=76, so it stops.

So it's missing messages 76-79. The issue is that the loop condition should be `len(messages) - size + overlap` or something similar to ensure the last window can be created.

A better loop condition would be:
```python
for start in range(0, max(1, len(messages) - size + overlap), step):
```

But even this might not work perfectly for all cases. Let me think of a more robust solution.

Actually, I think the best approach is to ensure that the last window always ends with the last message:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    # First window is straightforward
    windows.append(messages[:size])
    
    # Subsequent windows
    start = step
    while start < len(messages) - overlap:
        end = min(start + size - 1, len(messages))
        chunk = [messages[0]] + messages[start:end]
        windows.append(chunk)
        start += step
    
    # Ensure we have a window that ends with the last message
    if windows[-1][-1] != messages[-1]:
        last_start = max(len(messages) - size + overlap, 0)
        chunk = [messages[0]] + messages[last_start:]
        windows.append(chunk)
    
    return windows
```

But this is getting complex. Let me check how the tests handle this. Looking at `tests/test_windows.py`:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This test would catch the issue I'm describing if it existed. Let me calculate for 90 messages:
- size=40, overlap=4, step=36
- start positions: 0, 36, 72
- Window 0: 0-39
- Window 1: [0] + 36-71
- Window 2: [0] + 72-107 (but 107>89, so 72-89)

So the last window ends at 89, which is correct.

Wait, the loop condition is `range(0, len(messages) - overlap, step)`. For 90 messages, that's `range(0, 86, 36)`, which gives 0, 36, 72. All valid.

For 80 messages: `range(0, 76, 36)` gives 0, 36. Window at 36: [0] + 36-75. But 75 < 79, so it misses 76-79.

The test `test_last_window_ends_at_last_message` for 90 messages passes because 72+40-1=111, but it gets clamped to 89. But for 80 messages, the last window would end at 75, not 79.

Let's check the test `test_windows_cover_every_message`:
```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test would fail for n=80 because messages 76-79 would be missing.

Let me verify with n=80:
- Window 0: 0-39
- Window 1: 0, 36-75
- Messages covered: 0-39, 36-75 = 0-75
- Missing: 76-79

So the test would fail for n=80, but it's not in the test cases. The test cases are 41, 76, 90, 157.

For n=76:
- Window 0: 0-39
- Window 1: 0, 36-75
- Messages covered: 0-39, 36-75 = 0-75
- Missing: 76? Wait, n=76 means messages 0-75, so it's covered.

For n=76, the last message is 75, which is covered by window 1.

For n=77:
- Window 0: 0-39
- Window 1: 0, 36-75
- Missing: 76

So the test would fail for n=77.

Given that the test cases don't include values like 77, 80, etc., there could be an issue with the window splitting algorithm for certain trajectory lengths.

Let me check the implementation again:

```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

The condition `len(messages) - overlap` ensures that the window has at least `overlap` messages beyond `start`. But for the last window, we want it to end at the last message, even if it means having fewer than `size` messages.

A better approach would be:

```python
for start in range(0, len(messages), step):
    end = min(start + size, len(messages))
    chunk = messages[start:end]
    if start > 0:
        chunk = [messages[0]] + chunk
    windows.append(chunk)
    if end == len(messages):
        break
```

This ensures that we cover all messages, with the last window potentially being shorter than `size`.

Actually, let's reconsider. The current implementation is trying to ensure that consecutive windows overlap by `overlap` messages. The condition `len(messages) - overlap` is meant to ensure that there are at least `overlap` messages after `start` for the overlap. But this means the last window might not reach the end of the messages.

A more robust approach would be:

```python
start = 0
while start < len(messages):
    end = min(start + size, len(messages))
    chunk = messages[start:end]
    
    # For windows after the first, include message 0 (instructions)
    if start > 0:
        chunk = [messages[0]] + chunk
    
    windows.append(chunk)
    
    # Move to next window, ensuring overlap
    if end == len(messages):
        break
    
    start += step
```

This way, we always cover all messages, with the last window ending at the last message.

Let me test this with n=80, size=40, overlap=4:
- Window 0: start=0, end=40, chunk=0-39
- start += 36 -> start=36
- Window 1: start=36, end=76, chunk=[0] + 36-75
- start += 36 -> start=72
- Window 2: start=72, end=80, chunk=[0] + 72-79

This covers all messages.

Actually, I think the current implementation is fine for most cases, but it might miss the very end of trajectories in some edge cases. The test cases in `test_windows.py` don't cover all edge cases, which is a problem.

Let's look at another issue:

In commit 6d5d3cb, the `score_trajectory` function normalizes the score with `normalise(worst.score)`. However, `worst.score` is an integer from 1-10, and `normalise` maps it to 0-1. But what if all windows fail to produce a valid score? The code doesn't handle this case. It assumes at least one window will succeed.

Actually, the code raises an exception if any window fails, so if one window fails, the whole trajectory scoring fails. This is consistent with the error handling in the pipeline.

Let me check the code:

```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
verdicts = [parse_reply(reply) for reply in replies]
worst = max(verdicts, key=lambda v: v.score)
```

If any call to `client.complete` or `parse_reply` fails, the whole thing fails. This is by design, as per the docstring: "Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails".

So this isn't a bug, just a design decision.

Let me look for other potential issues.

In commit 806d5c7, the `iter_trajectory_batches` function uses `cursor.fetchmany(batch_size)`. However, if the database connection is used elsewhere concurrently, this could lead to unexpected behavior. But since this is a nightly job that likely has exclusive access to the database, this isn't a major concern.

Another issue I noticed: In commit 6d5d3cb, the `build_request` function was modified to include window position information:

```python
f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
```

But `traj.n_messages` might not be accurate if the trajectory has been truncated or processed in some way. However, it seems like `traj.n_messages` is set when the trajectory is loaded from the database, so it should be correct.

Actually, looking at the `Trajectory` class (which isn't fully shown in the diff), it's likely that `n_messages` is populated from the database query, so it should be accurate.

Another potential issue: In commit 412637b, the `parse_reply` function was made stricter, raising an error for any malformed reply. However, in commit 6d5d3cb, the code was modified to use windowed scoring. If one window has a malformed reply but others are fine, the whole trajectory is marked as an error. This might be too strict; perhaps we should only consider the successfully parsed windows.

But according to the design, if any window fails, the whole trajectory scoring fails. This is consistent with the approach of being strict about monitor reliability.

Let me check if there are any performance concerns.

In commit 6d5d3cb, the code uses `ThreadPoolExecutor` to process windows concurrently. For trajectories with many windows, this could lead to a large number of concurrent requests to the monitor. However, the code limits this with `max_workers=min(cfg.monitor.max_workers, len(requests))`, so it's not a concern.

Actually, I think the most significant issue is with the window splitting algorithm potentially missing the end of some trajectories. The test cases don't cover all edge cases, which means this bug might have slipped through.

Let me propose a fix for the `split_windows` function:

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
    start = 0
    
    while start < len(messages):
        end = min(start + size, len(messages))
        chunk = messages[start:end]
        
        # For windows after the first, include message 0 (instructions)
        if start > 0:
            chunk = [messages[0]] + chunk
        
        windows.append(chunk)
        
        # If this window reached the end, we're done
        if end == len(messages):
            break
        
        # Move to next window, ensuring we maintain the overlap
        start += step
    
    return windows
```

This approach ensures that:
1. All messages are covered
2. Windows overlap by the specified amount
3. The last window ends with the last message
4. Subsequent windows include the first message (instructions)

Let me verify with a few examples:

Example 1: 80 messages, size=40, overlap=4
- Window 0: start=0, end=40, chunk=0-39
- start=0+36=36
- Window 1: start=36, end=76, chunk=[0]+36-75
- start=36+36=72
- Window 2: start=72, end=80, chunk=[0]+72-79
- Done

Example 2: 41 messages, size=40, overlap=4
- Window 0: start=0, end=40, chunk=0-39
- start=0+36=36
- Window 1: start=36, end=41, chunk=[0]+36-40
- Done

Example 3: 76 messages, size=40, overlap=4
- Window 0: start=0, end=40, chunk=0-39
- start=0+36=36
- Window 1: start=36, end=76, chunk=[0]+36-75
- Done (since end=76 == len(messages))

This seems to handle all cases correctly.

Let me check if there's a test case for 41 messages in `test_windows.py`:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

Yes, 41 is included, and the current implementation passes for 41. But with the current implementation:

For n=41:
- len(messages)-overlap = 41-4 = 37
- range(0, 37, 36) = [0]
- Window 0: 0-39

This misses message 40. So the test should fail for n=41, but it's listed as a test case that passes. This suggests the current implementation might already handle this case correctly, or there's a mistake in my analysis.

Wait, for n=41:
- Window 0: start=0, chunk=messages[0:40] = 0-39
- That's it, because 0+36=36, and 36 >= 41-4=37? No, 36 < 37, so there would be a second iteration.
- start=36, chunk=messages[36:76] but 76>41, so it's 36-40
- For start>0, it becomes [0] + 36-40

So messages covered: 0-39, 0, 36-40 = 0-40. All messages are covered.

For n=41, len(messages)-overlap = 37, and range(0, 37, 36) gives [0, 36]. So it does create two windows.

For n=80, len(messages)-overlap = 76, and range(0, 76, 36) gives [0, 36, 72]. So it creates three windows:
- 0: 0-39
- 36: [0] + 36-75
- 72: [0] + 72-111 (but clamped to 72-79)

All messages are covered.

So my earlier analysis was incorrect. The current implementation does handle these cases correctly.

Let me reconsider. The loop condition is `range(0, len(messages) - overlap, step)`. For n=80, overlap=4, this is `range(0, 76, 36)`, which gives 0, 36, 72.

- Window at 0: messages[0:40]
- Window at 36: messages[36:76]
- Window at 72: messages[72:112] -> clamped to 72:80

For start>0, it prepends message 0, so:
- Window 0: 0-39
- Window 1: 0, 36-75
- Window 2: 0, 72-79

All messages are covered: 0-39, 36-75, 72-79 = 0-79.

So the implementation is correct. My mistake was in thinking that `messages[72:112]` would be clamped to 72-111, but in Python, slicing beyond the end of a list just gives up to the end of the list.

Given this, the window splitting algorithm seems correct.

Let me look for other potential issues.

In commit 6d5d3cb, the `normalise` function is defined as:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

But MIN_SCORE and MAX_SCORE are defined in `parse.py`:

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This creates a dependency between modules. If these constants ever change, it could lead to inconsistencies. It would be better to define these constants in a shared location or pass them explicitly.

However, given that these are fundamental to the scoring system and unlikely to change, this might not be a significant issue.

Another potential issue: In commit 412637b, the `parse_reply` function was made stricter, but in commit 6d5d3cb, the code was modified to use windowed scoring. The error messages don't indicate which window failed, which could make debugging harder.

For example, in `score_trajectory`:

```python
try:
    result = score_trajectory(traj, client, cfg, system_prompt)
except (MonitorParseError, MonitorUnavailable) as exc:
    log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
```

This logs the error, but doesn't specify which window caused the issue. This could make it harder to diagnose problems.

A simple improvement would be to include the window index in the error message.

However, this isn't a bug, just a potential enhancement for debugging.

Let me look at the `decide` function in commit 6d5d3cb:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This is correct, but what if `score` is NaN or infinity? This is unlikely given the normalization function, but it's worth considering.

The normalization function:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Given that `raw` is an integer between 1 and 10 (enforced by `parse_reply`), and MIN_SCORE=1, MAX_SCORE=10, this will always produce a float between 0.0 and 1.0. So there's no risk of NaN or infinity.

Let me check if there are any issues with the new `run_metrics` table added in commit ba3f0fa.

The `write_metrics` function:

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

This looks correct, but I notice that `s.alert_rate` is calculated as `stats.alerts / self.scored if self.scored else 0.0` in `RunSummary.finalise()`. However, `self.scored` is the total number of trajectories scored, not the number for that deployment. This means `alert_rate` is calculated as `alerts / total_scored`, not `alerts / deployment_scored`.

Let's check:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is incorrect. The alert rate for a deployment should be `alerts / scored` for that deployment, not divided by the total number of scored trajectories.

For example, if:
- Total scored: 100
- Deployment A: scored=50, alerts=10 -> alert rate should be 20%
- Deployment B: scored=50, alerts=5 -> alert rate should be 10%

But with the current code:
- Deployment A alert rate: 10/100 = 10%
- Deployment B alert rate: 5/100 = 5%

This is a bug. The alert rate should be calculated per deployment.

The fix would be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me verify this with the test case in `tests/test_pipeline.py`:

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

This test checks that metrics are recorded for each deployment, but it doesn't verify the alert rate calculation. So the bug might have slipped through.

This is a significant issue because it means the alert rates reported in `run_metrics` are incorrect. They're being calculated as (deployment alerts) / (total scored) instead of (deployment alerts) / (deployment scored).

Let me double-check the code from commit ba3f0fa:

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

Yes, this is definitely calculating the alert rate as (deployment alerts) / (total scored), which is incorrect. It should be (deployment alerts) / (deployment scored).

This is the most significant bug I've found in the commit chain.

Let me check if there are any other issues.

In commit 6d5d3cb, the `score_trajectory` function uses `worst = max(verdicts, key=lambda v: v.score)` to find the highest score. This is correct for identifying the worst window, but the rationale is taken from that window. This is by design, as the docstring says: "the trajectory gets the highest window score: one clearly bad window is enough to alert."

However, it might be useful to include information about which window had the highest score in the rationale or in the database. But this isn't a bug, just a potential enhancement.

Another issue: In commit 6d5d3cb, the `build_request` function was modified to include the window position:

```python
f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
```

But `traj.n_messages` might not be accurate if the trajectory has been truncated or processed. However, it seems like `traj.n_messages` is populated from the database, so it should be the total number of messages in the trajectory.

Actually, looking at the `Trajectory` class (which isn't fully shown), it's likely that `n_messages` is set when the trajectory is loaded from the database, so it should be accurate.

Given the analysis, the most significant issue is the incorrect calculation of `alert_rate` in `RunSummary.finalise()`. This should be fixed.

Let me draft a follow-up commit to address this:

```
fix: calculate per-deployment alert rate correctly

The alert rate for each deployment was being calculated as
(deployment alerts) / (total scored trajectories) instead of
(deployment alerts) / (deployment scored trajectories).

This commit fixes the calculation to use the deployment's own
scored count for the denominator.

MON-2258
```

The code change would be:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -43,7 +43,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me verify this with an example:
- Total scored: 100
- Deployment A: scored=50, alerts=10 -> alert rate = 10/50 = 20%
- Deployment B: scored=50, alerts=5 -> alert rate = 5/50 = 10%

This is the correct calculation.

I think this is the most important fix needed. There might be other minor improvements, but this is a clear bug that should be addressed.
