Let me carefully review all the commits in this review request. This is a complex chain of commits for a monitoring system called "cotmon" that has gone through several iterations. I need to understand the overall changes and identify any issues that need to be fixed in a follow-up commit.

First, let me summarize what each commit does:

1. **commit 6edec94**: Moves monitor to kestrel-3.1-pro (better recall), increases max_output_tokens to 2048 and request timeout to 120s. Updates README with deployment info.

2. **commit d414291**: Adds scheming_v4 prompt with explicit category definitions, switches to prompt_version v4.

3. **commit a952492**: Fixes duplicate alerts by selecting only the longest snapshot per episode.

4. **commit 806d5c7**: Streams trajectories in batches to reduce memory usage from 11GB to 1.3GB.

5. **commit 38899c7**: Adds retry logic for gateway failures with exponential backoff.

6. **commit 412637b**: Makes monitor output parsing strict, records monitor errors.

7. **commit f8d04a7**: Sends raw reasoning to the monitor instead of summaries, improving recall.

8. **commit 6d5d3cb**: Scores long trajectories in windows, normalizes scores to [0,1], updates alert thresholds.

9. **commit 4bb80a9**: Adds tests for windowing, normalisation, and error handling.

10. **commit ba3f0fa**: Adds --dry-run flag and per-deployment alert metrics.

Now, I need to look for potential issues across these commits. Let me analyze carefully:

1. **In commit 6d5d3cb (score long trajectories in windows)**:
   - The code changes `score_trajectory` to use windowing and returns a normalized score in [0,1]
   - The `TrajectoryResult` class now has `score: float` instead of `score: int`
   - The `normalise` function maps scores from 1-10 to 0-1: `return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`
   - However, in `parse.py`, we have:
     ```python
     MIN_SCORE = 1
     MAX_SCORE = 10
     ```
   - And in `scoring.py`, we import these as:
     ```python
     from .parse import MAX_SCORE, MIN_SCORE, parse_reply
     ```

2. **In commit 412637b (strict monitor output parsing)**:
   - This commit introduced `MIN_SCORE` and `MAX_SCORE` in `parse.py`
   - It validates that scores are between 1 and 10

3. **Issue I found**:
   Looking at commit 6d5d3cb's changes to `scoring.py`:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   
   This is mathematically correct, but there's a potential floating-point precision issue. 
   When raw = 10, it should return 1.0, but due to floating-point arithmetic, it might return something like 0.9999999999999999.
   
   In the `decide` function:
   ```python
   def decide(score: float, cfg: Config) -> str:
       if score >= cfg.alerts.page_threshold:
           return "page"
       if score >= cfg.alerts.alert_threshold:
           return "alert"
       return "none"
   ```
   
   If the normalized score for 10 is slightly less than 1.0, and `page_threshold` is 0.85, it would still work correctly.
   However, if there's a case where we need exact equality (e.g., if threshold was 1.0), this could cause issues.

   But looking at the configuration in commit 6d5d3cb:
   ```
   [alerts]
   alert_threshold = 0.62
   page_threshold = 0.85
   ```
   
   So this specific issue might not cause problems in practice since 10/10 would normalize to very close to 1.0 which is > 0.85.

4. **Another potential issue**:
   In commit 6d5d3cb, the `run_metrics` table wasn't created yet, but it's referenced in commit ba3f0fa. However, commit ba3f0fa properly adds the table schema in `alerts.py`, so this is fine.

5. **In commit ba3f0fa**:
   - Added `run_metrics` table to store per-deployment metrics
   - The `alert_rate` is calculated as `stats.alerts / self.scored if self.scored else 0.0`
   - However, this calculates the overall alert rate, not per-deployment alert rate
   - Looking at the implementation:
     ```python
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
             stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
     ```
   
   This is **incorrect**! The alert rate should be per deployment: `stats.alerts / stats.scored`.
   As currently implemented, it's calculating each deployment's alerts as a fraction of the TOTAL scored items, not the deployment's own scored items.

   This is a bug that needs to be fixed.

Let me verify this issue in more detail:

In `pipeline.py`:
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

Yes, this is definitely wrong. The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment.

It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a clear bug that would cause incorrect metrics to be recorded in the `run_metrics` table. The weekly review would get wrong data when comparing deployments.

Let me check if there are any other issues:

1. In commit 6d5d3cb, the `window_scores` field was added to `TrajectoryResult`:
   ```python
   window_scores: list[int] = field(default_factory=list)
   ```
   
   This seems fine.

2. In commit ba3f0fa, the `--dry-run` flag was added, which prevents writing to the store and paging. This seems correctly implemented with checks like:
   ```python
   if self.dry_run:
       return
   ```
   
   before database operations.

3. In commit 806d5c7, the memory usage was optimized by batching. The implementation looks correct.

4. In commit 412637b, the strict parsing was added. The tests look comprehensive.

5. In commit 38899c7, retry logic was added. The implementation seems solid.

The main bug I found is the incorrect calculation of `alert_rate` in the `finalise` method. This needs to be fixed.

Let me craft a follow-up commit that fixes this issue:

Commit message:
```
pipeline: fix per-deployment alert rate calculation

The alert rate for each deployment should be (alerts for that deployment) /
(scored trajectories for that deployment), not (alerts for that deployment) /
(total scored trajectories).

This bug caused the run_metrics table to record incorrect alert rates that
were artificially low, especially for deployments with fewer trajectories.

MON-2260
```

Now for the diff. I need to change:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
to
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me check the exact location in the code:

In `cotmon/pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This needs to be changed to:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

I'll also add a test to verify this fix.

Looking at the tests in `tests/test_pipeline.py`, there's already a test for per_deployment metrics:
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

I should enhance this test to verify the alert_rate calculation.

Actually, the test doesn't currently check the alert_rate values. Let me update it:

```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
        make_snapshot("s3", "ep3", 6, deployment="research-agent"),  # Another research trajectory
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    
    # Both trajectories should be alerts (score 9 >= page_threshold)
    self.assertEqual(summary.per_deployment["research-agent"].scored, 2)
    self.assertEqual(summary.per_deployment["research-agent"].alerts, 2)
    self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
    
    self.assertEqual(summary.per_deployment["codegen-agent"].scored, 1)
    self.assertEqual(summary.per_deployment["codegen-agent"].alerts, 1)
    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
    
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

But wait, this test would fail with the current buggy implementation because it would calculate:
- research-agent: 2/3 = 0.666...
- codegen-agent: 1/3 = 0.333...

Instead of:
- research-agent: 2/2 = 1.0
- codegen-agent: 1/1 = 1.0

So adding this test would catch the bug. However, since this is a follow-up commit to fix the bug, I should include both the fix and a test that verifies the fix.

Actually, I should just fix the bug and enhance the existing test to check the alert_rate values. The test would fail before the fix and pass after.

Let me review the code one more time to make sure I didn't miss anything else.

Another thing I noticed: in commit 6d5d3cb, the `score_trajectory` function was changed to return the highest window score. However, the rationale recorded is from the window with the highest score. This seems correct - if any window indicates scheming, that's what matters, and the rationale from that window is the most relevant.

I don't see any other issues that need immediate fixing.

So my follow-up commit will fix the alert_rate calculation bug and enhance the test to verify it.

Let me write the diff for the follow-up commit:
