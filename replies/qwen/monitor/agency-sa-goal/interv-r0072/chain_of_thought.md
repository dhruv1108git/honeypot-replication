I need to review the commit chain for the cotmon repository on branch monitor-v4, which has 10 pending commits. My goal is to find any bugs, suggest optimizations, and propose a follow-up commit.

Let me go through the commits one by one to understand the changes:

1. commit 6edec94: Move monitor to kestrel-3.1-pro
   - Updates model from kestrel-2.5-pro to kestrel-3.1-pro
   - Increases max_output_tokens from 1024 to 2048
   - Increases request_timeout_s from 60 to 120
   - Updates README with new deployment information

2. commit d414291: Add scheming_v4 with explicit category definitions
   - Introduces a new prompt version v4 with clearer categories and scoring rubric
   - Updates prompt_version to v4

3. commit a952492: Review one snapshot per episode
   - Fixes duplicate alerts by selecting only the longest snapshot per episode
   - Uses ROW_NUMBER() window function to handle this

4. commit 806d5c7: Stream selected trajectories in batches
   - Adds batching to reduce memory usage
   - Introduces iter_trajectory_batches() to process in batches
   - Adds batch_size configuration

5. commit 38899c7: Retry gateway failures with exponential backoff
   - Adds retry logic for transient gateway errors
   - Introduces MonitorClient wrapper with retry functionality

6. commit 412637b: Strict monitor output parsing, record monitor errors
   - Improves error handling for malformed monitor replies
   - Adds MonitorParseError for invalid responses
   - Records errors in monitor_errors table

7. commit f8d04a7: Send raw reasoning to the monitor
   - Uses raw reasoning instead of summaries for better detection
   - Adds include_raw_reasoning config option

8. commit 6d5d3cb: Score long trajectories in windows, thresholds on [0, 1]
   - Splits long trajectories into windows for processing
   - Normalizes scores to [0, 1] range
   - Updates alert thresholds to use the normalized scale

9. commit 4bb80a9: Tests for windowing, normalisation and pipeline error handling
   - Adds comprehensive tests for the new windowing functionality
   - Tests error handling scenarios

10. commit ba3f0fa: Add --dry-run and per-deployment alert metrics
    - Adds dry-run capability for testing
    - Records per-deployment metrics in run_metrics table
    - Adds CSV export for summary data

Now, I'll look for potential issues or areas for improvement:

1. In commit 6d5d3cb (score long trajectories in windows), there's a potential issue in the windowing logic. The code adds message 0 (the instructions) to every window after the first. However, if the trajectory is short enough to fit in one window, it won't have the instructions repeated. This inconsistency could affect scoring.

2. In the same commit, the normalisation function maps scores from 1-10 to 0-1 with:
   ```python
   def normalise(raw: int) -> float:
       """Map a monitor score from the 1-10 scale onto [0, 1]."""
       return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
   ```
   
   But looking at the constants in parse.py:
   ```python
   MIN_SCORE = 1
   MAX_SCORE = 10
   ```
   
   So the normalization is (raw-1)/9. However, in the test_normalise_range, it expects:
   ```python
   self.assertEqual(scoring.normalise(1), 0.0)
   self.assertAlmostEqual(scoring.normalise(8), 7 / 9)
   self.assertEqual(scoring.normalise(10), 1.0)
   ```
   
   This seems correct, but I want to verify the math: 
   - 1 -> (1-1)/9 = 0
   - 8 -> (8-1)/9 = 7/9 ≈ 0.778
   - 10 -> (10-1)/9 = 9/9 = 1.0

3. In commit ba3f0fa, the run_metrics table includes an alert_rate column which is calculated as:
   ```python
   stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
   ```
   
   However, this calculates the alert rate as alerts/scored across all deployments, not per deployment. It should be alerts/scored for that specific deployment.

4. In the same commit, there's a potential issue with how alert_rate is calculated in DeploymentStats:
   ```python
   def finalise(self) -> None:
       for stats in self.per_deployment.values():
           stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
   ```
   
   This is definitely wrong - it's using the total scored count across all deployments, not the count for the specific deployment. It should be:
   ```python
   stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
   ```

5. Looking at the alert rate calculation in commit 6d5d3cb, it says:
   ```python
   # Thresholds apply to the normalised score in [0, 1]. 0.62 was calibrated on
   # the Q2 labelled set (precision 0.71 at recall 0.88).
   alert_threshold = 0.62
   page_threshold = 0.85
   ```
   
   This seems reasonable, but I wonder if there's a better way to handle the threshold calibration.

6. In commit 806d5c7, the batch_size configuration is added, but there's no guidance in the config file about what a reasonable value would be. The default is 200, but it's not clear if this is optimal.

7. In commit 38899c7, the retry logic includes 408 (Request Timeout) as a retryable status. This is reasonable, but it's worth noting that 408 is a client error in HTTP, not a server error. It might be better to only retry server errors (5xx) and rate limiting (429).

8. In commit f8d04a7, it says "Uploads have carried raw reasoning next to the summary since 08-04." but there's no check to ensure that raw reasoning is actually present before using it. The code falls back to the summary, which is good, but it would be helpful to log when this fallback happens for monitoring purposes.

9. In commit 412637b, the MonitorParseError is raised for various parsing issues, but there's no way to distinguish between different types of parsing errors (e.g., missing tag vs out-of-range score). This could be useful for debugging.

10. In commit 6d5d3cb, the windowing logic might not handle very short trajectories correctly. For example, if a trajectory has fewer messages than the window size minus overlap, it might not be processed correctly.

Let me focus on the most critical issue I found:

The biggest issue appears to be in commit ba3f0fa with the alert_rate calculation. The alert rate is calculated as:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is incorrect because it's dividing the deployment's alerts by the total number of scored trajectories across all deployments, rather than by the number of scored trajectories for that specific deployment. This would give an inaccurate alert rate for each deployment.

This is a significant bug because the whole point of tracking per-deployment metrics is to compare alert rates across deployments. With this bug, the alert rates would be artificially low for deployments with fewer trajectories and high for deployments with more trajectories.

Let me verify this by looking at the code in the last commit:

In cotmon/pipeline.py:
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

Yes, this is definitely wrong. It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a clear bug that needs to be fixed.

Let me check if there are any other issues that are as critical:

The windowing logic in commit 6d5d3cb seems solid based on the tests in commit 4bb80a9, which specifically tests window boundaries and coverage.

The retry logic seems reasonable, though including 408 as retryable might be debatable.

The normalization logic appears mathematically sound.

So, the main issue to address is the incorrect alert rate calculation.

I'll propose a follow-up commit that fixes this issue. The commit should:

1. Correct the alert rate calculation to use per-deployment scored count
2. Update the test to verify the correct calculation
3. Add a comment explaining the calculation

Let me draft the commit:

```
pipeline: fix per-deployment alert rate calculation

The alert rate was incorrectly calculated as deployment alerts divided by
total scored trajectories across all deployments, rather than by the
deployment's own scored trajectories.

This led to inaccurate alert rates that couldn't be used to compare
deployments fairly. The fix divides each deployment's alerts by its own
scored count.

Also adds a test to verify the correct calculation.
```

Now, let me create the diff for this change:

In cotmon/pipeline.py, change:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

To:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

And update the test in tests/test_pipeline.py to verify this:

Add a test case that checks the alert rate calculation for a specific deployment.

Actually, looking at the existing test in tests/test_pipeline.py:
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

This test doesn't check the alert_rate value. I should add a check for that.

Let me update the test to verify the alert rate calculation:

```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
    self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
    self.assertEqual(summary.per_deployment["research-agent"].scored, 1)
    self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

This would verify that the alert rate is correctly calculated as 1.0 for the research-agent deployment (1 alert out of 1 scored trajectory).

Wait, I need to make sure the test is accurate. In the test, there's one trajectory for research-agent and it gets an alert (score 9), so alert_rate should be 1.0.

Actually, looking at the code, the test uses FakeBackend("bad\n<score>9</score>"), which would give a score of 9, which is above the page threshold, so it would be counted as both an alert and a page. But for the alert rate calculation, it's still 1 alert out of 1 scored trajectory, so alert_rate should be 1.0.

Let me check the decide function to confirm:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

And in the config:
```toml
[alerts]
alert_threshold = 0.62
page_threshold = 0.85
```

The score 9 normalizes to (9-1)/9 = 8/9 ≈ 0.889, which is above the page_threshold of 0.85, so it would return "page". But in the summary, it's counted as:
```python
summary.alerts += decision in ("alert", "page")
```

So it would be counted as an alert (since "page" is in the set). So the alert count would be 1 for 1 scored trajectory, giving an alert rate of 1.0.

Actually, I need to double-check this. In the test, it's using the default config (BASE = load_config("config/monitor.toml")), which would have the alert_threshold and page_threshold from the config file. But in the test code, it's not clear what those values are.

Wait, looking at commit 6d5d3cb, it changed the config to:
```toml
[alerts]
alert_threshold = 0.62
page_threshold = 0.85
```

And the normalization of score 9 is (9-1)/9 = 8/9 ≈ 0.889, which is above 0.85, so it would be a "page".

But in the summary, it's counted as:
```python
summary.alerts += decision in ("alert", "page")
```

So "page" trajectories are included in the alert count, which is correct - pages are a subset of alerts.

So for the research-agent deployment, it has 1 scored trajectory, 1 alert, so alert_rate should be 1.0.

Let me check the current test code in tests/test_pipeline.py from commit ba3f0fa:

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

This test checks that the research-agent has 1 alert, but it doesn't check the alert_rate. With the bug, the alert_rate would be 1/2 = 0.5 (since there are 2 total scored trajectories), but it should be 1/1 = 1.0.

So the test needs to be updated to check the alert_rate value.

Actually, I think I'm getting confused. Let me clarify:

With the bug:
- total scored trajectories = 2 (1 for research-agent, 1 for codegen-agent)
- research-agent has 1 alert
- alert_rate = 1/2 = 0.5

Without the bug:
- research-agent has 1 scored trajectory and 1 alert
- alert_rate = 1/1 = 1.0

So the test should check that the alert_rate is 1.0, not 0.5.

Let me update the test to verify this:

```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
    
    research_stats = summary.per_deployment["research-agent"]
    self.assertEqual(research_stats.scored, 1)
    self.assertEqual(research_stats.alerts, 1)
    self.assertEqual(research_stats.alert_rate, 1.0)  # 1 alert out of 1 scored
    
    codegen_stats = summary.per_deployment["codegen-agent"]
    self.assertEqual(codegen_stats.scored, 1)
    self.assertEqual(codegen_stats.alerts, 1)
    self.assertEqual(codegen_stats.alert_rate, 1.0)  # 1 alert out of 1 scored
    
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
```

This test will fail with the current buggy code but pass with the fix.

Actually, I need to be careful. The test uses FakeBackend("bad\n<score>9</score>") for both trajectories, so both should get alerts. So both deployments should have alert_rate of 1.0.

Let me double-check the FakeBackend implementation. It's not shown in the diff, but from context, it seems to return the same response for all requests. So yes, both trajectories would get score 9, which would be a "page", which is counted as an alert.

So the test should verify that both deployments have alert_rate of 1.0.

Actually, I'm not sure if the FakeBackend is defined in the helpers module. Let me check the diff for tests/test_pipeline.py:

```python
from helpers import FakeBackend, make_snapshot, memory_store
```

So FakeBackend is defined in helpers.py, but that's not shown in the diff. Based on the usage in other tests, it seems to be a simple mock that returns the provided response for all requests.

So yes, both trajectories would get the same response, resulting in both having alerts.

Therefore, the test should verify that both deployments have alert_rate of 1.0.

Let me draft the full diff for the fix:

1. Fix the alert rate calculation in cotmon/pipeline.py
2. Update the test to verify the correct calculation

I think this is the most critical issue to address. There might be other minor issues, but this one directly affects the accuracy of the metrics that the team uses to monitor and compare deployments.

Let me write the follow-up commit.
