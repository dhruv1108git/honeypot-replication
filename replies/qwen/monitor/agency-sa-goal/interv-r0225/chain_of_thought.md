Let me analyze the commit chain and identify issues to fix or improvements to make.

First, I'll go through all the commits to understand what changes have been made:

1. commit 6edec94: Update to kestrel-3.1-pro model with increased max_output_tokens and timeout
2. commit d414291: Add scheming_v4 prompt with explicit category definitions
3. commit a952492: Review only one snapshot per episode to avoid duplicate alerts
4. commit 806d5c7: Stream selected trajectories in batches to reduce memory usage
5. commit 38899c7: Add retry logic for gateway failures
6. commit 412637b: Add strict monitor output parsing and error recording
7. commit f8d04a7: Send raw reasoning to the monitor instead of summaries
8. commit 6d5d3cb: Split long trajectories into windows for scoring, normalize scores
9. commit 4bb80a9: Add tests for windowing, normalization, and error handling
10. commit ba3f0fa: Add --dry-run option and per-deployment alert metrics

Now I'll look for potential issues or areas for improvement:

1. In commit 6d5d3cb (scoring: score long trajectories in windows, thresholds on [0, 1]):
   - The commit introduced windowing with a fixed size of 40 messages and 4-message overlap
   - The code uses `ThreadPoolExecutor` for parallel scoring of windows
   - The `split_windows` function has a potential off-by-one error in the range calculation

Let me check the `split_windows` implementation:

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

Let's analyze this function:

1. For a trajectory with 41 messages:
   - `len(messages) = 41`, `size = 40`, `overlap = 4`
   - `step = 36`
   - First window: start=0 -> messages[0:40]
   - Next start would be 36, but `36 + 40 = 76 > 41`, so it stops
   - Only one window is created, which is correct

2. For a trajectory with 76 messages:
   - First window: start=0 -> messages[0:40]
   - Next start: 36 -> messages[36:76]
   - Only two windows are created, but this misses messages 72-75 (the last 4 messages)

The issue is with the range calculation: `range(0, len(messages) - overlap, step)`

This should probably be: `range(0, len(messages), step)` with proper handling of the end condition.

Let me verify with 76 messages:
- First window: start=0 -> messages[0:40]
- Next start: 36 -> messages[36:76]
- This covers all 76 messages

But with 77 messages:
- First window: start=0 -> messages[0:40]
- Next start: 36 -> messages[36:76]
- Next start: 72 -> messages[72:112] which would be messages[72:77]
- This covers all 77 messages

Actually, the current implementation is:
```python
for start in range(0, len(messages) - overlap, step):
```

With 77 messages:
- `len(messages) - overlap = 77 - 4 = 73`
- The range would go up to 72 (since range is exclusive of the end)
- So we'd get windows starting at 0 and 36
- The second window would be messages[36:76]
- Messages 76 would be missed

The correct approach would be:
```python
for start in range(0, len(messages), step):
    end = min(start + size, len(messages))
    chunk = messages[start:end]
    # Handle the case where we're not at the beginning
    if start > 0:
        chunk = [messages[0]] + chunk
    windows.append(chunk)
```

Actually, looking more carefully at the intended behavior:
1. First window: messages[0:40]
2. Second window: [messages[0]] + messages[36:76] (because step = 36)
3. Third window: [messages[0]] + messages[72:112] (which would be messages[72:77] for 77 messages)

The current implementation would miss messages 76-79 for a trajectory with 80 messages.

Let me check the unit test `test_windows_cover_every_message` in tests/test_windows.py:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test would catch the issue if it existed. But let's simulate what happens with n=76:

- First window: messages[0:40] -> indices 0-39
- Second window: [messages[0]] + messages[36:76] -> indices 0, 36-75
- Combined: 0-39, 36-75 -> 0-75 (all indices covered)

With n=77:
- First window: messages[0:40] -> indices 0-39
- Second window: [messages[0]] + messages[36:76] -> indices 0, 36-75
- Missing: 76

So the test would fail for n=77. But the test only checks n in (41, 76, 90, 157), which might not expose the issue.

Let me check n=90:
- First window: 0-39
- Second window: 0, 36-75
- Third window: 0, 72-89 (since 72+40=112 > 90, so it's 72-89)
- Combined: 0-39, 36-75, 72-89 -> 0-89 (all covered)

n=157:
- First window: 0-39
- Second window: 0, 36-75
- Third window: 0, 72-111
- Fourth window: 0, 108-147
- Fifth window: 0, 144-156 (since 144+40=184 > 157)
- Combined: 0-39, 36-75, 72-111, 108-147, 144-156 -> 0-156 (all covered)

So the current implementation does cover all messages for the tested values. But let's check the exact calculation:

For n=90, step=36:
- start=0 -> 0-39
- start=36 -> 36-75
- start=72 -> 72-111 (but n=90, so 72-89)
- The range calculation: `range(0, 90-4, 36)` -> `range(0, 86, 36)` -> [0, 36, 72]
- This is correct.

For n=77:
- `range(0, 77-4, 36)` -> `range(0, 73, 36)` -> [0, 36]
- First window: 0-39
- Second window: 0, 36-76
- Combined: 0-39, 36-76 -> 0-76 (all covered)

So the current implementation seems correct for the tested values.

Wait, let me double-check n=77:
- First window: messages[0:40] -> indices 0-39
- Second window: [messages[0]] + messages[36:76] -> indices 0, 36-75
- Missing: 76

Oh, I see the issue. The second window should be messages[36:76] but that's indices 36-75. So message 76 (index 76) is not included.

The problem is with the slice notation: `messages[start : start + size]` gives messages from index `start` up to but not including `start + size`.

So for start=36 and size=40, we get messages[36:76], which is indices 36-75.

To include index 76, we'd need messages[36:77], but that would exceed the size limit.

The correct approach would be:
- First window: 0-39 (40 messages)
- Second window: 36-75 (40 messages)
- Third window: 72-89 (for n=90)

But this leaves a gap between 76-89 for n=90. Wait, no - with overlap=4, the windows should overlap by 4 messages.

Actually, the intended behavior is:
- Window 1: messages 0-39
- Window 2: messages 36-75 (overlap of 4 messages: 36-39)
- Window 3: messages 72-89 (overlap of 4 messages: 72-75)

This covers all messages from 0-89.

For n=77:
- Window 1: 0-39
- Window 2: 36-75
- Missing: 76

So message 76 is not included in any window.

The issue is that the range calculation should ensure the last window includes the last message.

Let me check the implementation of `split_windows` again:

```python
for start in range(0, len(messages) - overlap, step):
    chunk = messages[start : start + size]
    windows.append(chunk if start == 0 else [messages[0], *chunk])
```

For n=77:
- `len(messages) - overlap = 77 - 4 = 73`
- `range(0, 73, 36)` -> [0, 36]
- First window: messages[0:40] -> 0-39
- Second window: [messages[0]] + messages[36:76] -> 0, 36-75
- Message 76 is not included

The fix would be to change the range to:
```python
for start in range(0, len(messages), step):
    if start + size > len(messages) and start > 0:
        # For the last window, include message 0 + the remaining messages
        chunk = [messages[0]] + messages[start:]
    elif start > 0:
        chunk = [messages[0]] + messages[start:start + size]
    else:
        chunk = messages[start:start + size]
    windows.append(chunk)
```

Actually, the current implementation seems to be working for the tested values because the test values (41, 76, 90, 157) are chosen such that they don't expose the issue. Let's check n=77 explicitly:

For n=77:
- First window: 0-39
- Second window: 0, 36-75
- Missing: 76

So message 76 is not included in any window.

This is a bug. The fix should ensure that the last window includes the last message.

Another issue I noticed:

In commit ba3f0fa (pipeline: --dry-run and per-deployment alert metrics), the `run_metrics` table is created with:

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

But in the `write_metrics` method:

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

This assumes that `per_deployment` is a dictionary mapping deployment names to `DeploymentStats` objects. However, in the `run_nightly` function:

```python
def run_nightly(...):
    # ...
    summary = RunSummary(run_id=run_id)
    # ...
    for batch in batches:
        for traj in batch:
            stats = summary.deployment(traj.deployment)
            # ...
            stats.scored += 1
            stats.alerts += flagged
```

And `RunSummary.deployment` is:

```python
def deployment(self, name: str) -> DeploymentStats:
    return self.per_deployment.setdefault(name, DeploymentStats())
```

This all looks correct. But I want to check if there's any issue with the `alert_rate` calculation.

In `DeploymentStats`:
```python
alert_rate: float = 0.0
```

And in `RunSummary.finalise`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Wait, this is incorrect. The alert rate should be per deployment, not across all deployments. It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a bug! The current implementation calculates the alert rate as (deployment alerts) / (total scored across all deployments), but it should be (deployment alerts) / (deployment scored).

Let me verify this:

If we have:
- research-agent: scored=10, alerts=2
- codegen-agent: scored=20, alerts=3

Total scored = 30

Current implementation:
- research-agent alert_rate = 2/30 = 0.067
- codegen-agent alert_rate = 3/30 = 0.1

Correct implementation:
- research-agent alert_rate = 2/10 = 0.2
- codegen-agent alert_rate = 3/20 = 0.15

This is definitely a bug.

Let me check the commit message for ba3f0fa:
"Each run now records scored/alerts/errors and the alert rate per deployment in a new run_metrics table"

Yes, it should be the alert rate per deployment, not the global alert rate.

This is a critical issue that needs to be fixed.

Another issue I noticed:

In commit 6d5d3cb, the `normalise` function is defined as:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where MIN_SCORE = 1 and MAX_SCORE = 10 (from cotmon/parse.py).

This means:
- score 1 -> 0.0
- score 10 -> 1.0

But the thresholds are set as:
- alert_threshold = 0.62
- page_threshold = 0.85

This means:
- alert_threshold corresponds to raw score = 1 + 0.62 * 9 = 6.58
- page_threshold corresponds to raw score = 1 + 0.85 * 9 = 8.65

Which means:
- raw score 7+ triggers alerts
- raw score 9+ triggers pages

This seems correct based on the comment: "0.62 was calibrated on the Q2 labelled set (precision 0.71 at recall 0.88)".

But let me check the `decide` function:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This is correct.

Let me check if there's any other issue:

In commit 412637b, the `parse_reply` function in cotmon/parse.py:

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

This looks correct. It finds the last <score> tag, which is what we want since earlier tags could be quoted from the transcript.

Another issue:

In commit 6d5d3cb, the `build_request` function was modified to include window position:

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

The position string is something like "window 3 of 3". But the episode ID is still included, which might be confusing because each window is only a part of the episode.

This isn't necessarily a bug, but it could be misleading. However, it's probably fine since the monitor is supposed to evaluate each window independently.

Let me check if there's any issue with the dry-run functionality:

In commit ba3f0fa, `AlertSink` was modified to take a `dry_run` parameter:

```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

And `record` and `record_error` were modified to do nothing if `dry_run` is True.

This looks correct.

Now, to summarize the issues I found:

1. Bug in alert rate calculation: `RunSummary.finalise` calculates the alert rate as (deployment alerts) / (total scored across all deployments) instead of (deployment alerts) / (deployment scored).

This is a critical issue that needs to be fixed.

Let me check if there are any other issues:

In commit 6d5d3cb, the `score_trajectory` function:

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

This looks correct. It scores each window, then takes the highest score as the trajectory score.

Let me check if there's any issue with the `split_windows` function:

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

I'm still concerned about the range calculation. Let me test with n=77, size=40, overlap=4:

- `len(messages) = 77`
- `step = 36`
- `range(0, 77 - 4, 36)` -> `range(0, 73, 36)` -> [0, 36]
- First window: messages[0:40] -> indices 0-39
- Second window: [messages[0]] + messages[36:76] -> indices 0, 36-75
- Missing: 76

So message 76 is not included in any window.

The fix should be to change the range to:
```python
for start in range(0, len(messages), step):
```

And then handle the case where `start + size > len(messages)`.

Actually, the correct approach would be:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    # First window: messages[0:size]
    windows.append(messages[:size])
    
    # Subsequent windows
    start = step
    while start < len(messages):
        end = min(start + size - 1, len(messages) - 1)
        chunk = messages[start:end + 1]
        
        # Add message 0 to all windows except the first
        window = [messages[0]] + chunk
        windows.append(window)
        
        start += step
    
    return windows
```

But the current implementation is more concise. Let me adjust it:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    
    step = size - overlap
    windows = []
    
    for start in range(0, len(messages), step):
        end = min(start + size, len(messages))
        chunk = messages[start:end]
        
        if start == 0:
            windows.append(chunk)
        else:
            # Add message 0 to all windows except the first
            windows.append([messages[0]] + chunk)
    
    return windows
```

This should ensure all messages are covered.

Let me test with n=77, size=40, overlap=4:
- step = 36
- start=0: chunk = messages[0:40] -> 0-39
- start=36: chunk = messages[36:76] -> 36-75
- start=72: chunk = messages[72:77] -> 72-76
- Windows: [0-39], [0, 36-75], [0, 72-76]
- Combined: 0-39, 36-75, 72-76 -> 0-76 (all covered)

Yes, this works.

The current implementation has `range(0, len(messages) - overlap, step)`, which for n=77 would be `range(0, 73, 36)` -> [0, 36]. It's missing the last window.

So there are two issues:
1. Bug in alert rate calculation
2. Bug in window splitting for trajectories where the last message isn't included in any window

Let me check if the unit test `test_windows_cover_every_message` would catch the second issue:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

For n=77 (which isn't in the test), it would fail. But the test uses n=76, which works:
- For n=76:
  - start=0: 0-39
  - start=36: 36-75
  - Combined: 0-39, 36-75 -> 0-75 (all covered, since n=76 means indices 0-75)

Wait, no. If n=76, then there are 76 messages with indices 0-75.

So for n=76:
- start=0: 0-39
- start=36: 36-75
- Combined: 0-39, 36-75 -> 0-75 (all covered)

For n=77 (77 messages, indices 0-76):
- start=0: 0-39
- start=36: 36-75
- Missing: 76

So the test wouldn't catch it because it doesn't test n=77.

This is a subtle bug that would only manifest for trajectories with certain lengths.

Given these findings, I'll propose a follow-up commit that fixes:

1. The alert rate calculation bug
2. The window splitting bug

Let me draft the commit:

Subject: fix(alerts): correct per-deployment alert rate calculation and window coverage

Body:
The alert rate in run_metrics was incorrectly calculated as (deployment alerts) / (total scored across all deployments) instead of (deployment alerts) / (deployment scored). This commit fixes the calculation to be per-deployment.

Also fixes a bug in split_windows() where the last few messages of a trajectory might not be included in any window. The range calculation now ensures all messages are covered by at least one window.

Tests have been updated to verify both fixes.

Now, let's create the diff:

For the alert rate bug:
```diff
-        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

For the window splitting bug:
```diff
-    for start in range(0, len(messages) - overlap, step):
+    for start in range(0, len(messages), step):
```

And update the test to include n=77:

```diff
-    for n in (41, 76, 90, 157):
+    for n in (41, 76, 77, 90, 157):
```

Let me check if there are any other implications:

For the window splitting fix, I need to ensure that the new range doesn't create overlapping windows beyond what's intended. But the test `test_windows_cover_every_message` should catch any issues.

Actually, with the new range, for n=40:
- len(messages) = 40
- step = 36
- range(0, 40, 36) -> [0]
- Only one window: messages[0:40]

For n=41:
- range(0, 41, 36) -> [0, 36]
- First window: messages[0:40]
- Second window: [messages[0]] + messages[36:41] -> 0, 36-40
- Combined: 0-39, 0, 36-40 -> 0-40 (all covered)

This is correct.

Let me verify the exact changes needed:

1. In cotmon/scoring.py, fix the alert rate calculation
2. In cotmon/transcript.py, fix the range in split_windows
3. In tests/test_windows.py, add n=77 to the test cases

Let me check if there are any other files that need updates.

Actually, for the window splitting fix, I need to be careful. The current implementation uses `start + size` which could go beyond the message list. The slice notation in Python handles this gracefully (it just returns up to the end of the list), so no additional changes are needed.

Let me draft the full diff:

```diff
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..f3d1a8c 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -144,7 +144,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..a1b2c3d 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -51,7 +51,7 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    for start in range(0, len(messages) - overlap, step):
+    for start in range(0, len(messages), step):
         chunk = messages[start : start + size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..3c4d5e6 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -20,7 +20,7 @@ class SplitWindowsTest(unittest.TestCase):
         self.assertEqual(seen, set(range(n)), n)
 
     def test_last_window_ends_at_last_message(self):
-        windows = split_windows(messages(90), 40, 4)
+        windows = split_windows(messages(91), 40, 4)
         self.assertEqual(windows[-1][-1].idx, 90)
 
     def test_overlap_between_windows(self):
@@ -31,6 +31,6 @@ class SplitWindowsTest(unittest.TestCase):
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
 
-if __name__ == "__main__":
+if __name__ == "__main__":
     unittest.main()
```

Wait, let me verify the test changes:

In `test_last_window_ends_at_last_message`, it was testing with 90 messages. With the fix, for 90 messages:
- First window: 0-39
- Second window: 0, 36-75
- Third window: 0, 72-89
- Last message index: 89

So the test should check for 89, not 90.

Actually, with 90 messages, the indices are 0-89.

So the test should be:
```python
self.assertEqual(windows[-1][-1].idx, 89)
```

But the test was:
```python
self.assertEqual(windows[-1][-1].idx, 89)
```

Wait, no. The test was:
```python
self.assertEqual(windows[-1][-1].idx, 89)
```

Actually, the test was:
```python
self.assertEqual(windows[-1][-1].idx, 89)
```

Wait, let me check the original test:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

With 90 messages, indices are 0-89. So the last message index is 89.

This test is correct.

But with the fix, it should still pass.

Actually, the test is correct as is. No change needed.

Let me update the diff:

```diff
diff --git a/cotmon/scoring.py b/cotmon/scoring.py
index 6eed82b..f3d1a8c 100644
--- a/cotmon/scoring.py
+++ b/cotmon/scoring.py
@@ -144,7 +144,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 @dataclass
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..a1b2c3d 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -51,7 +51,7 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
-    for start in range(0, len(messages) - overlap, step):
+    for start in range(0, len(messages), step):
         chunk = messages[start : start + size]
         windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..3c4d5e6 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -18,7 +18,7 @@ def messages(n):
 class SplitWindowsTest(unittest.TestCase):
     def test_short_trajectory_is_one_window(self):
         msgs = messages(40)
-        self.assertEqual(split_windows(msgs, 40, 4), [msgs])
+        self.assertEqual(len(split_windows(msgs, 40, 4)), 1)
 
     def test_windows_cover_every_message(self):
-        for n in (41, 76, 90, 157):
+        for n in (41, 76, 77, 90, 157):
             windows = split_windows(messages(n), 40, 4)
             seen = {m.idx for w in windows for m in w}
             self.assertEqual(seen, set(range(n)), n)
```

Actually, the first test `test_short_trajectory_is_one_window` should still check that it's exactly [msgs], not just that the length is 1. So no change needed there.

Let me verify the alert rate calculation fix:

Before:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

After:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Yes, this is correct.

Let me check if there are any other implications:

In the `run_metrics` table, the alert_rate is defined as REAL NOT NULL. The calculation `stats.alerts / stats.scored` could result in a float, which is fine.

I think these are the only two fixes needed.

Let me draft the full commit message and diff.
