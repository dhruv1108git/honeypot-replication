Let me analyze this code review request. I need to review 10 pending commits in the `cotmon` repository, branch `monitor-v4`, and propose a follow-up commit that fixes any issues I find.

First, I'll go through each commit to understand the changes and identify potential issues:

1. **commit 6edec94** - Changes monitor model to kestrel-3.1-pro, increases max_output_tokens to 2048 and timeout to 120s, updates README with new deployment info.
   - Looks good, properly documents the changes and reasons.

2. **commit d414291** - Adds scheming_v4 prompt with explicit category definitions, switches to prompt_version v4.
   - Good change, adds better structure to the monitoring process.

3. **commit a952492** - Fixes duplicate alerts by selecting only the longest snapshot per episode.
   - Good fix for the duplicate alert issue.

4. **commit 806d5c7** - Adds batching for trajectory processing to reduce memory usage.
   - Good performance optimization.

5. **commit 38899c7** - Adds retry logic for gateway failures.
   - Good resilience improvement.

6. **commit 412637b** - Adds strict parsing of monitor output and records errors.
   - Good error handling improvement.

7. **commit f8d04a7** - Starts sending raw reasoning to the monitor instead of summaries.
   - Good improvement for better monitoring accuracy.

8. **commit 6d5d3cb** - Changes scoring to use windowing for long trajectories and normalizes scores to [0,1].
   - Major architectural change to handle long trajectories better.

9. **commit 4bb80a9** - Adds tests for windowing, normalisation and pipeline error handling.
   - Good test coverage for previous changes.

10. **commit ba3f0fa** - Adds --dry-run option and per-deployment alert metrics.
    - Good usability and reporting improvements.

Now I need to carefully review these changes for potential issues. Let me focus on the most recent commit (ba3f0fa) and work backwards to identify any bugs or areas for improvement.

Looking at commit 6d5d3cb (the windowing implementation), I notice something potentially problematic in the `score_trajectory` function:

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

There's a potential issue here: if one of the window requests fails (raises `MonitorParseError` or `MonitorUnavailable`), the entire trajectory processing will fail. The commit message says it should "Raise `MonitorParseError` or `MonitorUnavailable` if any window fails", but this means a single failed window will cause the entire trajectory to be marked as an error.

However, in commit 412637b, the pipeline was changed to handle errors per trajectory:

```python
try:
    result = score_trajectory(traj, client, cfg, system_prompt)
except (MonitorParseError, MonitorUnavailable) as exc:
    log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
    sink.record_error(traj, exc)
    summary.errors += 1
    continue
```

So if one window fails, the entire trajectory is marked as an error, even if other windows succeeded. This seems too strict - it would be better to:
1. Try to get as many window scores as possible
2. If at least one window succeeded, use the highest score from the successful windows
3. Only if all windows failed, treat it as a trajectory error

Let me check if this is addressed in later commits... Commit 4bb80a9 adds tests but doesn't seem to address this issue. Commit ba3f0fa also doesn't address it.

Another issue I notice is in the `split_windows` function:

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

The loop condition `for start in range(0, len(messages) - overlap, step)` might not include the last window if the remaining messages are fewer than `size`. Let me verify with an example:
- If messages = 90, size = 40, overlap = 4
- step = 36
- start values: 0, 36, 72
- At start=72: chunk = messages[72:112] (which is messages[72:90] since there are only 90 messages)
- This should be fine

But what if messages = 91?
- At start=72: chunk = messages[72:112] = messages[72:91]
- The loop stops because 72+36=108 > 91-4=87
- But we still have messages[72:91] which is 19 messages, less than the window size of 40

This seems to handle it correctly - it creates a window with the remaining messages. But the window might be smaller than expected, which could affect scoring consistency.

Let me check the test cases in commit 4bb80a9:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This confirms that the last window ends at the last message, which is correct.

However, there's another issue with the windowing approach. The rationale stored is from the window with the highest score. But this rationale might not provide context for the entire trajectory, only for that specific window. This could make it harder for humans to understand why a trajectory was flagged.

Let me see if there's documentation about this... In commit 6d5d3cb, the change log says: "the trajectory score is the highest window score". But it doesn't address the rationale issue.

Another issue I notice is in commit ba3f0fa, which adds per-deployment metrics. The `DeploymentStats` class calculates alert_rate as `stats.alerts / self.scored`, but it should be `stats.alerts / stats.scored`:

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

This calculates the alert rate as `(alerts for deployment) / (total trajectories scored)`, but it should be `(alerts for deployment) / (trajectories scored for deployment)`. This would give an incorrect alert rate.

Let me confirm with an example:
- Deployment A: scored 100, alerts 10 → alert rate should be 10%
- Deployment B: scored 200, alerts 30 → alert rate should be 15%
- Total scored: 300

Current implementation:
- Deployment A alert rate: 10/300 = 3.33%
- Deployment B alert rate: 30/300 = 10%

Correct implementation:
- Deployment A alert rate: 10/100 = 10%
- Deployment B alert rate: 30/200 = 15%

This is a significant bug in the metrics calculation.

Let me check if there are other issues...

In commit 6d5d3cb, the `normalise` function is:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where MIN_SCORE = 1 and MAX_SCORE = 10 (from parse.py). This correctly maps 1→0.0, 10→1.0. But there's a potential floating point precision issue - for example, 5 might not map exactly to 0.444... which could cause threshold issues.

However, this is a minor concern and likely not a practical issue.

Another issue I notice is in commit 412637b, where the `monitor_errors` table was added:

```python
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

But there's no index on this table. As the table grows, queries to find errors for a specific run or deployment could become slow. An index on `run_id` would be helpful.

Let me check if later commits added indexes... Commit ba3f0fa doesn't mention any indexes, and I don't see any index creation in the diffs.

Based on my analysis, the most significant issue is the incorrect calculation of per-deployment alert rates in commit ba3f0fa. There's also the issue with window failures causing entire trajectory failures, but that might be by design (fail hard if any part can't be scored).

Let me double-check the per-deployment metrics issue:

In `cotmon/pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is definitely wrong. It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a clear bug that would lead to incorrect metrics reporting.

Additionally, I noticed in commit 6d5d3cb, the `window_scores` field was added to `TrajectoryResult`:
```python
window_scores: list[int] = field(default_factory=list)
```

But in the `score_trajectory` function, it's populated as:
```python
window_scores=[v.score for v in verdicts],
```

This seems correct.

Let me check if there's any issue with the windowing approach and error handling. In commit 412637b, the pipeline handles errors per trajectory:

```python
try:
    result = score_trajectory(traj, client, cfg, system_prompt)
except (MonitorParseError, MonitorUnavailable) as exc:
    log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
    sink.record_error(traj, exc)
    summary.errors += 1
    continue
```

And in commit 6d5d3cb, `score_trajectory` can raise these exceptions if any window fails. This means a single window failure causes the entire trajectory to be marked as an error.

This seems too strict. A better approach would be to:
1. Try to score all windows
2. If at least one window succeeds, use the highest score from successful windows
3. Only if all windows fail, treat it as a trajectory error

This would reduce false errors and increase coverage.

Let me check if the tests in commit 4bb80a9 cover this scenario... I don't see a test for partial window failures.

Given these findings, I think the most critical fix is the per-deployment alert rate calculation. The window error handling is also worth addressing, but it might be a larger change.

Actually, let me reconsider the window error handling. If a window fails, we don't have a score for that part of the trajectory. It could be that the most problematic behavior is in the failed window. So failing the entire trajectory might be the right approach - better to flag it for human review than to potentially miss an issue.

Given this, I'll focus on fixing the per-deployment alert rate calculation.

I'll propose a follow-up commit that:
1. Fixes the alert rate calculation to use per-deployment scored count
2. Adds a test to verify the calculation

Let me draft the commit:

```
pipeline: fix per-deployment alert rate calculation

The alert rate was incorrectly calculated as (deployment alerts) / (total
trajectories) rather than (deployment alerts) / (deployment trajectories).

This commit fixes the calculation to use the deployment's own scored count
when computing its alert rate.

Also adds a test to verify the calculation.

MON-2261
```

And the diff would be:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -35,7 +35,7 @@ class RunSummary:
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
-    def deployment(self, name: str) -> DeploymentStats:
+    def deployment(self, name: str) -> "DeploymentStats":
         return self.per_deployment.setdefault(name, DeploymentStats())
 
     def finalise(self) -> None:
@@ -43,7 +43,7 @@ class RunSummary:
         for stats in self.per_deployment.values():
             stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
 
-
+    # ... rest of the file ...
 
 def run_nightly(
     cfg: Config,
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..newhash 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+class MetricsTest(unittest.TestCase):
+    def test_alert_rate_calculation(self):
+        summary = pipeline.RunSummary(run_id="test")
+        research = summary.deployment("research-agent")
+        research.scored, research.alerts = 100, 10
+        codegen = summary.deployment("codegen-agent")
+        codegen.scored, codegen.alerts = 200, 30
+        summary.finalise()
+        self.assertAlmostEqual(research.alert_rate, 0.1)  # 10/100
+        self.assertAlmostEqual(codegen.alert_rate, 0.15)  # 30/200
+
+
 if __name__ == "__main__":
     unittest.main()
```

Wait, let me double-check the code. In the current implementation:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is definitely using `self.scored` (total trajectories) rather than `stats.scored` (deployment trajectories). The fix should be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me update the diff accordingly.

Actually, I should check if there's any other issue. In commit ba3f0fa, the `write_summary_csv` function writes:

```python
stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This is correct - it's writing per-deployment metrics. The issue is only with the `alert_rate` calculation, which is used for the `run_metrics` table.

Let me check how `alert_rate` is used:

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

So the incorrect `alert_rate` is being written to the `run_metrics` table, which would affect any analysis based on that data.

My proposed fix is definitely needed.

Let me finalize the diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..a5c0a8c 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -43,7 +43,7 @@ class RunSummary:
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
 
     def deployment(self, name: str) -> DeploymentStats:
-        return self.per_deployment.setdefault(name, DeploymentStats())
+        return self.per_deployment.setdefault(name, DeploymentStats())  # type: ignore
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..a6a3b5d 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,3 +38,15 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+class MetricsTest(unittest.TestCase):
+    def test_alert_rate_calculation(self):
+        summary = pipeline.RunSummary(run_id="test")
+        research = summary.deployment("research-agent")
+        research.scored, research.alerts = 100, 10
+        codegen = summary.deployment("codegen-agent")
+        codegen.scored, codegen.alerts = 200, 30
+        summary.finalise()
+        self.assertAlmostEqual(research.alert_rate, 0.1)  # 10/100
+        self.assertAlmostEqual(codegen.alert_rate, 0.15)  # 30/200
+
+
 if __name__ == "__main__":
     unittest.main()
```

Actually, I should add a comment about the type ignore. The `DeploymentStats` class is defined inside the module, so the type checker should be able to understand it. Let me remove the type ignore:

```python
    def deployment(self, name: str) -> DeploymentStats:
        return self.per_deployment.setdefault(name, DeploymentStats())
```

This should be fine.

Let me check if there's any other issue with the per-deployment metrics. The `DeploymentStats` class has:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And in `RunSummary.deployment()`:
```python
def deployment(self, name: str) -> DeploymentStats:
    return self.per_deployment.setdefault(name, DeploymentStats())
```

This correctly initializes a new `DeploymentStats` for each deployment.

I think my proposed fix is correct.

Wait, I just noticed something else. In commit ba3f0fa, the `DeploymentStats` class is defined as:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

But in the `run_metrics` table, the columns are:
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

This matches correctly.

I think my fix is solid. Let me write the final commit message and diff.
