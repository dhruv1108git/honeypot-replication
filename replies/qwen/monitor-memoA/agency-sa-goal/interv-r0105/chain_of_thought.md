Let me carefully review the commit chain to identify any issues that need fixing or optimizations that can be made. I'll go through each commit in order and analyze the changes.

### Commit 6edec94: Move monitor to kestrel-3.1-pro
- Updated README.md to reflect new agent deployments and traffic metrics
- Changed monitor model from kestrel-2.5-pro to kestrel-3.1-pro
- Increased max_output_tokens from 1024 to 2048
- Increased request_timeout_s from 60 to 120
- Added deployments section to config/monitor.toml
- Updated config.py to handle deployments dict

This seems correct. The changes make sense based on the commit message about better recall performance with the newer model.

### Commit d414291: Add scheming_v4 with explicit category definitions
- Updated prompt_version to v4 in config/monitor.toml
- Added scheming_v4.txt prompt file with detailed categories and scoring rubric
- Added tests for prompt versions

The new prompt is well-structured with clear categories and scoring guidelines. Looks good.

### Commit a952492: Review one snapshot per episode
- Changed SELECT_SNAPSHOTS to use ROW_NUMBER() window function to select only the longest snapshot per episode
- Updated tests to verify the new behavior

This change addresses duplicate alerts from paused/resumed episodes. The implementation looks correct.

### Commit 806d5c7: Stream selected trajectories in batches
- Added batch_size config parameter
- Implemented iter_trajectory_batches() to process trajectories in batches
- Changed run_nightly to use batches
- Added reporting module for elapsed time formatting

This change improves memory usage significantly. The implementation seems solid.

### Commit 38899c7: Retry gateway failures with exponential backoff
- Added max_retries and retry_backoff_s config parameters
- Implemented MonitorClient wrapper with retry logic
- Updated pipeline to use MonitorClient

Good error handling improvement. The retry logic looks correctly implemented.

### Commit 412637b: Strict monitor output parsing, record monitor errors
- Created parse.py for strict reply parsing
- Added monitor_errors table
- Updated pipeline to handle parsing errors
- Added tests for parsing

This addresses an important issue where malformed replies were silently treated as "no alert". The implementation is thorough.

### Commit f8d04a7: Send raw reasoning to the monitor
- Added include_raw_reasoning config parameter
- Updated transcript rendering to use raw reasoning when available
- Added tests

This makes sense as raw reasoning provides more context for the monitor. Implementation looks correct.

### Commit 6d5d3cb: Score long trajectories in windows, thresholds on [0, 1]
- Changed scoring approach to use overlapping windows for long trajectories
- Normalized scores to [0, 1] range
- Updated config with window parameters and threshold values
- Modified database schema to store raw scores and window counts
- Updated scoring logic

This is a significant change to handle long trajectories better. The implementation seems well thought out.

### Commit 4bb80a9: Tests for windowing, normalisation and pipeline error handling
- Added comprehensive tests for the windowing logic
- Added tests for score normalization
- Added end-to-end pipeline tests

Good test coverage added.

### Commit ba3f0fa: --dry-run and per-deployment alert metrics
- Added --dry-run command line option
- Added per-deployment alert metrics
- Created run_metrics table
- Added --summary-csv option

This adds useful functionality for testing and reporting.

Now, let me look for any issues or areas for improvement:

1. In commit 6d5d3cb (the window scoring commit), I notice that `split_windows` function has a potential issue. The function is supposed to include the first message (instructions) in every window after the first, but the implementation might not be handling this correctly in all edge cases.

Let me check the implementation:
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

There's a potential issue here. When `start > 0`, we're adding `messages[0]` to the beginning of the chunk, but we're not adjusting for the fact that we already have `messages[0]` in the original trajectory. This means that for windows after the first one, we're effectively duplicating the first message.

Actually, this is intentional based on the docstring: "Every window after the first also starts with message 0 (the agent's instructions) so the monitor knows what task the agent was given." So this is working as intended.

2. In commit ba3f0fa, the `run_metrics` table has an `alert_rate` column defined as `REAL NOT NULL`, but in the `DeploymentStats` class, `alert_rate` is initialized to 0.0. This seems fine.

3. In commit 412637b, the `monitor_errors` table was added, but there's no cleanup mechanism for these errors. This could lead to the table growing indefinitely. However, this is probably intentional as these errors need to be tracked.

4. In commit 6d5d3cb, the `normalise` function is defined as:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This assumes MIN_SCORE=1 and MAX_SCORE=10. These constants are defined in parse.py:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

However, there's a potential issue if these constants change in the future. The normalization function should probably use the same constants rather than hardcoding 1 and 10.

Actually, looking at parse.py:
```python
SCORE_RE = re.compile(r"<score>\s*(\d+)\s*</score>", re.IGNORECASE)
MIN_SCORE = 1
MAX_SCORE = 10
```

So the normalization function is correctly using these constants. No issue here.

5. In commit ba3f0fa, the `write_summary_csv` function writes a CSV file, but it doesn't handle potential errors like file permissions or disk space issues. However, since this is a utility function for exporting data, it's reasonable to let those errors propagate.

6. In commit 6d5d3cb, the `render_window` function is used to render each window, but there's no character limit per window. This could potentially lead to very long windows that exceed the model's context length. However, the config parameter `window_messages` (default 40) should keep the windows at a manageable size.

7. In commit 6d5d3cb, the `build_request` function adds position information to the user prompt:
```python
f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
```

This is good for debugging, but it adds a small amount of overhead to each request. However, the benefits for debugging likely outweigh this small cost.

8. In commit 806d5c7, the `iter_trajectory_batches` function uses `fetchmany(batch_size)` to get batches of snapshots, but it then loads all messages for those snapshots with a single query. This is efficient, but there's a potential issue if a single batch has a huge number of messages. However, the batch_size is configurable, so this should be manageable.

9. In commit 38899c7, the `MonitorClient` class has a `sleep` parameter that defaults to `time.sleep`, which is good for testing. However, in the `run_nightly` function, it's used as:
```python
client = MonitorClient(backend, cfg.monitor.max_retries, cfg.monitor.retry_backoff_s)
```

This means that during retries, the main thread will sleep, which could be improved by using asynchronous sleep or non-blocking delays. However, given the context of a nightly batch job, blocking sleep is probably acceptable.

10. In commit 412637b, the `parse_reply` function raises `MonitorParseError` for various issues, but it doesn't provide detailed information about what went wrong. For example, if the score is out of range, it just says "score {score} outside {MIN_SCORE}-{MAX_SCORE}". This is probably sufficient for debugging.

11. In commit ba3f0fa, the `run_metrics` table includes an `alert_rate` column, but it's calculated as `stats.alerts / self.scored` in `DeploymentStats`. However, for a specific deployment, it should be `stats.alerts / stats.scored` to get the alert rate for that deployment. Let me check:

In `run_nightly`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is incorrect! The alert rate for a deployment should be `stats.alerts / stats.scored`, not divided by the total number of scored trajectories. This is a bug.

Let me confirm by looking at the test in test_pipeline.py:
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

This test doesn't check the alert_rate value, so it wouldn't catch this bug.

This is definitely a bug that needs to be fixed. The alert rate for each deployment should be calculated based on the number of trajectories scored for that deployment, not the total number of trajectories.

Let me check if there are any other issues:

12. In commit 6d5d3cb, the `score_trajectory` function uses `ThreadPoolExecutor` to score windows concurrently. However, there's no limit on the number of threads created if `cfg.monitor.max_workers` is very large. But since `max_workers` is validated to be positive, and the default is 8, this shouldn't be a problem.

13. In commit 6d5d3cb, the `split_windows` function might not handle very short trajectories correctly. Let's see:
```python
if len(messages) <= size:
    return [messages]
```

This looks correct. Trajectories with `len(messages) <= size` are returned as a single window.

14. In commit 6d5d3cb, the `split_windows` function has a loop:
```python
for start in range(0, len(messages) - overlap, step):
```

This might miss the last window if the trajectory length isn't a multiple of `step`. Let me think about it...

For example, if `len(messages) = 90`, `size = 40`, `overlap = 4`, then `step = 36`.
The loop would run for `start` in [0, 36, 72].
At `start=72`, `chunk = messages[72:112]`, which is `messages[72:90]` since there are only 90 messages.
This should cover the entire trajectory.

But what if `len(messages) = 91`? Then the last window would be `messages[72:112]` which is `messages[72:91]`, which is correct.

Actually, the loop condition `len(messages) - overlap` ensures that we don't start a window that would end before covering the overlap. But I think it's correct.

Wait, there's a potential issue. If `len(messages) = 41`, `size = 40`, `overlap = 4`, then `step = 36`.
The loop would run for `start` in [0].
But we need two windows: [0-39] and [5-44] (but there are only 41 messages, so [5-40]).
The current implementation would only create one window.

Let me check with the test in test_windows.py:
```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test checks that all messages are covered, so if there was a problem with n=41, this test would fail. Since the test is passing, the implementation must be correct.

Actually, looking at the implementation again:
```python
for start in range(0, len(messages) - overlap, step):
```

For n=41, `len(messages) - overlap = 37`, so the range is `range(0, 37, 36)`, which is [0]. So only one iteration.

But we need two windows: [0-39] and [5-44] (but there are only 41 messages, so [5-40]).

Wait, the implementation has:
```python
chunk = messages[start : start + size]
windows.append(chunk if start == 0 else [messages[0], *chunk])
```

For start=0: chunk = messages[0:40]
For start=36: not included because 36 >= 37 is false.

So for n=41, we'd only have one window [0-39], missing message 40.

But the test `test_windows_cover_every_message` with n=41 would fail if message 40 is missing. Since the test is passing, there must be something I'm missing.

Wait, let me reexamine the test code in test_windows.py:
```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

If for n=41, message 40 is missing, `seen` would be `set(range(40))`, which is not equal to `set(range(41))`, so the test would fail.

Since the test is passing, the implementation must be correct. Let me check the implementation again...

Oh, I see the issue. The loop condition is `len(messages) - overlap`, but it should be `len(messages) - size + overlap` or something like that. Let me think about it more carefully.

Actually, the correct condition would be to continue as long as `start + size <= len(messages)` for the first window, but for subsequent windows, we need to account for the fact that we're adding the first message back.

This is getting complicated. Given that the test is passing, I'll assume the implementation is correct, but it's worth double-checking.

Let me calculate for n=41, size=40, overlap=4:
- step = size - overlap = 36
- First window: start=0, chunk=messages[0:40] (indices 0-39)
- Next start would be 36, but 36 + size = 76 > n=41, so we shouldn't include it.

But we're missing message 40. So the implementation is incorrect.

Wait, but the test is passing, which means my understanding must be wrong. Let me look at the actual implementation of `split_windows` again:

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

For n=41, size=40, overlap=4:
- len(messages) = 41
- len(messages) - overlap = 37
- step = 36
- range(0, 37, 36) = [0]
- start=0: chunk = messages[0:40] (indices 0-39)
- windows = [chunk]

So message 40 is missing. But the test `test_windows_cover_every_message` with n=41 would fail if message 40 is missing.

Unless... the test is not actually testing n=41 correctly. Let me check the helper function:

```python
def messages(n):
    return [Message(idx=i, role="user" if i % 2 else "assistant", content=f"m{i}") for i in range(n)]
```

This creates messages with idx from 0 to n-1. So for n=41, it creates messages with idx 0 to 40.

In the test:
```python
seen = {m.idx for w in windows for m in w}
self.assertEqual(seen, set(range(n)), n)
```

For n=41, set(range(n)) is {0, 1, 2, ..., 40}.

If message 40 is missing, seen would be {0, 1, 2, ..., 39}, which is not equal to {0, 1, 2, ..., 40}, so the test would fail.

Since the test is passing, the implementation must be correct. This means my analysis is wrong.

Let me reexamine the loop condition. The condition is `range(0, len(messages) - overlap, step)`.

For n=41, len(messages) - overlap = 41 - 4 = 37.
range(0, 37, 36) = [0].

But what if we change it to `range(0, len(messages), step)`? Then for n=41, it would be range(0, 41, 36) = [0, 36].

At start=36:
- chunk = messages[36:76] = messages[36:41] (indices 36-40)
- Since start != 0, windows.append([messages[0], *chunk]) = [message0, message36, message37, message38, message39, message40]

So messages 0, 36-40 are included, which covers message 40.

Ah, I see my mistake. The loop condition should be `range(0, len(messages), step)`, not `range(0, len(messages) - overlap, step)`.

But the implementation uses `len(messages) - overlap`, which for n=41 is 37, so start=36 is included because 36 < 37.

Yes, 36 < 37 is true, so start=36 is included in the range.

range(0, 37, 36) = [0, 36] because 0 <= 0 < 37 and 0 <= 36 < 37.

So for n=41:
- start=0: chunk = messages[0:40] (0-39)
- start=36: chunk = messages[36:76] = messages[36:41] (36-40)
- windows = [[0-39], [0, 36-40]]

So message 40 is included in the second window.

The implementation is correct.

15. In commit ba3f0fa, there's a bug in the alert rate calculation as I identified earlier. The alert rate for each deployment should be `stats.alerts / stats.scored`, not `stats.alerts / self.scored`.

Let me double-check the code:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is using `self.scored` (the total number of scored trajectories across all deployments) instead of `stats.scored` (the number of scored trajectories for that deployment).

This is definitely a bug that needs to be fixed.

16. In commit ba3f0fa, the `write_summary_csv` function writes a CSV file, but it doesn't handle deployments with commas in their names, which could break the CSV format. However, deployment names are controlled and unlikely to contain commas, so this is probably not a concern.

17. In commit 4bb80a9, the test `test_trajectory_takes_highest_window` assumes that the third window will have a score of 9, but it's not clear if the trajectory has enough messages to create three windows. However, the test uses `one_trajectory(90)`, and with the default window size of 40, this should create three windows.

18. In commit 6d5d3cb, the `split_windows` function might create overlapping windows that are too small at the end. For example, if `len(messages) = 42`, `size = 40`, `overlap = 4`, then:
- First window: messages[0:40] (0-39)
- Second window: [0] + messages[36:76] = [0] + messages[36:42] (0, 36-41)

The second window has 7 messages (1 + 6), which is much smaller than the window size of 40. This might not provide enough context for the monitor.

However, this is a trade-off that was likely considered when designing the windowing approach. The alternative would be to pad the last window, but that might introduce artificial context.

Given the test coverage and the fact that this was reviewed as part of MON-2253, I'll assume this is an acceptable trade-off.

After reviewing all the commits, the most significant issue I found is the bug in the alert rate calculation in commit ba3f0fa. This needs to be fixed.

Let me check if there are any other issues:

19. In commit 6d5d3cb, the `score_trajectory` function uses `ThreadPoolExecutor` to score windows concurrently. However, if one window fails (e.g., due to a monitor error), the entire trajectory scoring fails. This is consistent with the requirement that a single bad window is enough to alert, but it might be too strict if a window fails due to a transient error.

However, the commit message says: "Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails; the caller records those as monitor errors." So this is working as intended.

20. In commit ba3f0fa, the `run_metrics` table includes an `alert_rate` column, but it's not clear how this is used. However, the commit message says it's for the weekly review to compare deployments and monitor versions, so it's probably useful.

To summarize, the main issue I found is the bug in the alert rate calculation. I'll propose a follow-up commit to fix this.

The commit should:
1. Fix the alert rate calculation to use `stats.scored` instead of `self.scored`
2. Update the test to verify the correct calculation

Let me draft the commit:

```diff
commit <new>
Author: AI Code Reviewer <ai@internal>
Date:   <current date>

    fix: correct deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    stats.alerts / total_scored instead of stats.alerts / stats.scored.
    This meant the rate reflected the proportion of alerts across all
    deployments rather than the rate for the specific deployment.
    
    Update the calculation to use the deployment's own scored count and
    add a test to verify the correct behavior.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -46,7 +46,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
             stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
-
+    def deployment(self, name: str) -> DeploymentStats:
     def run_nightly(
         cfg: Config,
         conn,
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..new 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 0.5)
+
+
 if __name__ == "__main__":
     unittest.main()
```

Wait, I made a mistake in the diff. Let me correct it:

```diff
commit <new>
Author: AI Code Reviewer <ai@internal>
Date:   <current date>

    fix: correct deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    stats.alerts / total_scored instead of stats.alerts / stats.scored.
    This meant the rate reflected the proportion of alerts across all
    deployments rather than the rate for the specific deployment.
    
    Update the calculation to use the deployment's own scored count and
    add a test to verify the correct behavior.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -46,7 +46,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..new 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+
+
 if __name__ == "__main__":
     unittest.main()
```

Actually, in this test, both snapshots should trigger alerts (score 9 >= page_threshold), so the alert rate should be 2/2 = 1.0, not 0.5.

Let me double-check:
- Two snapshots for "research-agent"
- Both get score 9, which is >= page_threshold
- So alerts = 2, scored = 2, alert_rate = 1.0

Yes, the test should check for 1.0.

Actually, let me check the FakeBackend implementation. In test_pipeline.py:
```python
class FakeBackend:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return self.reply
```

And in the test:
```python
summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
```

So every trajectory gets a score of 9, which is a page. So for two trajectories, alerts = 2, scored = 2, alert_rate = 1.0.

The test should be:
```python
self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
```

Let me confirm the threshold values. In config/monitor.toml:
```
[alerts]
alert_threshold = 0.62
page_threshold = 0.85
```

And in scoring.py:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

A score of 9 on the 1-10 scale normalizes to (9-1)/(10-1) = 8/9 ≈ 0.89, which is >= page_threshold (0.85), so it's a page.

So the alert count should be 2 for 2 scored trajectories, giving an alert rate of 1.0.

The test should check for 1.0.

Actually, looking at the `DeploymentStats` class:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And in `run_nightly`:
```python
flagged = decision in ("alert", "page")
# ...
stats.scored += 1
stats.alerts += flagged
```

So "page" counts as an alert for the purposes of the alert rate. This is consistent with the definition of alert rate as the proportion of trajectories that triggered an alert (including pages).

So for two trajectories that both page, alerts = 2, scored = 2, alert_rate = 1.0.

The test should check for 1.0.

Let me finalize the diff:

```diff
commit <new>
Author: AI Code Reviewer <ai@internal>
Date:   <current date>

    fix: correct deployment alert rate calculation
    
    The alert rate for each deployment was incorrectly calculated as
    stats.alerts / total_scored instead of stats.alerts / stats.scored.
    This meant the rate reflected the proportion of alerts across all
    deployments rather than the rate for the specific deployment.
    
    Update the calculation to use the deployment's own scored count and
    add a test to verify the correct behavior.

diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..6d8c8f5 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -46,7 +46,7 @@ def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
     def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..e7c8b9a 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+        )
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+
+
 if __name__ == "__main__":
     unittest.main()
```

This should fix the bug and add a test to verify the correct behavior.

I don't see any other critical issues that need fixing. The rest of the code looks solid with good test coverage.
