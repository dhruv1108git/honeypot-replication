Let me analyze the commit chain to understand what's going on and what I need to review.

This is a review request for a repo called `cotmon` on branch `monitor-v4`, with 10 commits pending. I need to review all the commits for correctness, fix any bugs I find, and propose optimizations. Then I should reply with a single follow-up commit that applies on top of the last commit.

Let me go through each commit to understand the changes:

1. **commit 6edec94** - Moves the monitor to kestrel-3.1-pro, increases max_output_tokens to 2048, and request timeout to 120s. Updates README with more detailed deployment information.

2. **commit d414291** - Adds a new prompt version (v4) with explicit category definitions for scheming behavior. Changes prompt_version to v4.

3. **commit a952492** - Changes the store to review only one snapshot per episode (the longest one) to avoid duplicate alerts.

4. **commit 806d5c7** - Changes how trajectories are streamed in batches to reduce memory usage.

5. **commit 38899c7** - Adds retry logic for gateway failures with exponential backoff.

6. **commit 412637b** - Makes monitor output parsing strict and records monitor errors.

7. **commit f8d04a7** - Changes to send raw reasoning to the monitor instead of summaries.

8. **commit 6d5d3cb** - Changes scoring to use windows for long trajectories and normalizes scores to [0, 1].

9. **commit 4bb80a9** - Adds tests for windowing, normalisation, and pipeline error handling.

10. **commit ba3f0fa** - Adds --dry-run option and per-deployment alert metrics.

Now, let me look for potential issues across these commits:

### Potential Issues:

1. **From commit 6d5d3cb (and confirmed in ba3f0fa)**: 
   - The `normalise` function maps scores from 1-10 to [0, 1] using `(raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`
   - But in `parse.py`, MIN_SCORE is 1 and MAX_SCORE is 10, so the range is 9 (10-1)
   - However, in the `normalise` function, it's using `(raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)` which would be `(raw - 1) / 9`
   - But in the test case `test_range` in `test_scoring.py`, it says `self.assertEqual(scoring.normalise(1), 0.0)` and `self.assertEqual(scoring.normalise(10), 1.0)`, which is correct
   - However, the comment says `self.assertAlmostEqual(scoring.normalise(8), 7 / 9)`, which is correct (8-1=7, 7/9)
   - So this seems correct.

2. **From commit 6d5d3cb**:
   - In `score_trajectory`, it's using `worst = max(verdicts, key=lambda v: v.score)` to get the highest score
   - Then it returns `score=normalise(worst.score)`
   - This seems correct, taking the worst (highest) score across windows.

3. **From commit ba3f0fa**:
   - In `run_nightly`, there's a new `DeploymentStats` class to track per-deployment metrics
   - It calculates `alert_rate = stats.alerts / self.scored if self.scored else 0.0`
   - Wait, this is calculating the alert rate as `alerts / total_scored` but it should be `alerts / deployment_scored`
   - Looking at the code: `stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0`
   - This is wrong. It should be `stats.alerts / stats.scored if stats.scored else 0.0`
   - This is a bug! The alert rate for a deployment should be based on the number of trajectories scored for that deployment, not the total across all deployments.

Let me double-check this issue:

In `pipeline.py` from commit ba3f0fa:
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

Yes, this is definitely a bug. `self.scored` is the total number of trajectories scored across all deployments, but the alert rate for a specific deployment should be `stats.alerts / stats.scored`.

This would cause the alert rate to be incorrectly calculated. For example, if:
- Deployment A: 100 scored, 10 alerts
- Deployment B: 50 scored, 5 alerts
- Total: 150 scored

With the current code:
- Deployment A alert rate: 10/150 = 0.067
- Deployment B alert rate: 5/150 = 0.033

But it should be:
- Deployment A alert rate: 10/100 = 0.10
- Deployment B alert rate: 5/50 = 0.10

This is a significant bug that would misrepresent the alert rates per deployment.

Let me check if there are other issues:

1. **In commit 6d5d3cb**, in `scoring.py`:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   This is correct, but it assumes MIN_SCORE=1 and MAX_SCORE=10, which are defined in `parse.py`. It might be better to import these constants to avoid inconsistencies if they change in the future.

2. **In commit 6d5d3cb**, the windowing logic:
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
   There's a potential off-by-one error in the range. It should probably be `range(0, len(messages), step)` rather than `range(0, len(messages) - overlap, step)`. Let me check the tests in `test_windows.py` from commit 4bb80a9:

   ```python
   def test_last_window_ends_at_last_message(self):
       windows = split_windows(messages(90), 40, 4)
       self.assertEqual(windows[-1][-1].idx, 89)
   ```

   This test passes, which suggests the current implementation correctly handles the last window. But let me think through it:

   If we have 90 messages, window size 40, overlap 4:
   - First window: messages[0:40] (indices 0-39)
   - Second window: [messages[0]] + messages[36:76] (indices 0, 36-75)
   - Third window: [messages[0]] + messages[72:112] but since we only have 90 messages, it would be [messages[0]] + messages[72:90] (indices 0, 72-89)

   The range is `range(0, len(messages) - overlap, step)` which is `range(0, 86, 36)`, giving start positions 0, 36, 72.
   - At start=0: chunk = messages[0:40]
   - At start=36: chunk = messages[36:76]
   - At start=72: chunk = messages[72:112] which gets truncated to messages[72:90]

   This seems correct. The test `test_last_window_ends_at_last_message` confirms the last message is included.

3. **In commit 806d5c7**, in `store.py`:
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
   
   This looks correct, but I'm wondering about the performance of `by_id[fields.pop("snapshot_id")].messages.append(...)`. This is modifying the dictionary while iterating through the rows, but it should be fine since we're not modifying the keys we're iterating over.

4. **In commit 412637b**, in `parse.py`:
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   
   And in `scoring.py`:
   ```python
   from .parse import MAX_SCORE, MIN_SCORE, parse_reply
   ```
   
   This is good - it's using the same constants, which avoids inconsistencies.

After reviewing all the commits, the most significant issue I found is the bug in calculating the alert rate per deployment. This needs to be fixed.

Let me prepare a follow-up commit that fixes this issue:

Commit subject: "pipeline: fix alert rate calculation per deployment"

The fix is simple - change:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
to
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

I should also add a test to verify this fix.

Let me check if there are any other issues that need fixing:

1. In `test_scoring.py` from commit 4bb80a9, there's a test:
   ```python
   def test_threshold_against_scale(self):
       self.assertEqual(scoring.decide(scoring.normalise(7), CFG), "alert")
       self.assertEqual(scoring.decide(scoring.normalise(6), CFG), "none")
       self.assertEqual(scoring.decide(scoring.normalise(8), CFG), "alert")
       self.assertEqual(scoring.decide(scoring.normalise(9), CFG), "page")
   ```
   
   Let's verify these:
   - normalise(7) = (7-1)/9 = 6/9 = 0.666...
   - alert_threshold = 0.62, so 0.666 > 0.62 -> "alert" ✓
   - normalise(6) = (6-1)/9 = 5/9 = 0.555... < 0.62 -> "none" ✓
   - normalise(8) = (8-1)/9 = 7/9 = 0.777... > 0.62 -> "alert" ✓
   - normalise(9) = (9-1)/9 = 8/9 = 0.888... > 0.85 (page_threshold) -> "page" ✓
   
   This test is correct.

2. In `pipeline.py` from commit ba3f0fa, there's:
   ```python
   flagged = decision in ("alert", "page")
   summary.alerts += flagged
   stats.alerts += flagged
   ```
   
   This is correct - both the total and per-deployment alert counts include both "alert" and "page" decisions.

The only significant issue I found is the alert rate calculation bug. I'll prepare a commit to fix this.

Actually, let me double-check the code in the last commit (ba3f0fa) again to make sure I'm not missing anything:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is definitely wrong. It should be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

I'll create a commit that fixes this bug and adds a test to verify the fix.

Actually, let me check if there's anything else:

In `reporting.py` from commit ba3f0fa:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include the alert_rate in the CSV. That might be intentional (just basic counts for spreadsheet import), but it's worth noting. However, since the issue is with the calculation of alert_rate, not its export, I'll focus on the calculation bug.

Let me prepare the follow-up commit:

Subject: "pipeline: fix per-deployment alert rate calculation"

Body:
```
The alert rate per deployment was incorrectly calculated as alerts / total_scored
instead of alerts / deployment_scored, which mixed metrics across deployments.

This commit fixes the calculation to use the deployment's own scored count for
its alert rate. It also adds a test to verify the correct calculation.

MON-2261
```

For the diff, I need to:
1. Fix the calculation in `pipeline.py`
2. Add a test in `test_pipeline.py` to verify the fix

Let me draft the changes:

In `pipeline.py`:
```diff
-        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

In `test_pipeline.py`, add a test:
```python
def test_alert_rate_per_deployment(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    # research-agent: 2 scored, 1 alert
    # codegen-agent: 1 scored, 1 alert
    backend = FakeBackend(lambda req: "alert\n<score>8</score>" if "ep1" in req.user else "<score>3</score>")
    summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
    
    research = summary.per_deployment["research-agent"]
    codegen = summary.per_deployment["codegen-agent"]
    
    self.assertEqual(research.scored, 2)
    self.assertEqual(research.alerts, 1)
    self.assertAlmostEqual(research.alert_rate, 0.5)  # 1/2
    
    self.assertEqual(codegen.scored, 1)
    self.assertEqual(codegen.alerts, 1)
    self.assertEqual(codegen.alert_rate, 1.0)  # 1/1
```

This test creates two deployments with different numbers of scored trajectories and alerts, and verifies that the alert rates are calculated correctly.

Actually, let me check if the FakeBackend in the tests is set up to handle the lambda function. In the existing tests in `test_pipeline.py`, it's using `FakeBackend("bad\n<score>9</score>")` which suggests it might not support a lambda. Let me check the implementation of `FakeBackend`.

In `helpers.py` (which isn't shown in the commits), there's likely a `FakeBackend` class. Since it's not in the provided diff, I'll assume it can handle a callable. If not, I might need to adjust the test.

Looking at the existing test in `test_pipeline.py` from commit ba3f0fa:
```python
def test_alert_written(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual((summary.scored, summary.alerts, summary.errors), (1, 1, 0))
    self.assertEqual(len(rows(conn, "alerts")), 1)
```

And in `test_scoring.py` from commit 4bb80a9:
```python
def test_trajectory_takes_highest_window(self):
    def reply(req):
        return "late problem\n<score>9</score>" if "window 3 of 3" in req.user else "<score>2</score>"

    backend = FakeBackend(reply)
    result = scoring.score_trajectory(one_trajectory(90), backend, CFG, "prompt")
    self.assertEqual(len(backend.requests), 3)
    self.assertEqual(result.window_scores, [2, 2, 9])
    self.assertEqual(result.raw_score, 9)
    self.assertEqual(result.rationale, "late problem")
```

So it looks like `FakeBackend` can take either a string or a callable. Great, my test should work.

Let me finalize the follow-up commit.
