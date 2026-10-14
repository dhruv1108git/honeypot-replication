Let me carefully review all the commits in this chain to identify any issues or opportunities for improvement.

First, let's understand the overall changes in this branch:

1. Commit 6edec94: Moves to kestrel-3.1-pro model, increases output tokens and timeout, updates README with new deployment info
2. Commit d414291: Adds prompt version v4 with explicit category definitions
3. Commit a952492: Fixes duplicate alerts by selecting only the longest snapshot per episode
4. Commit 806d5c7: Adds batching for memory efficiency
5. Commit 38899c7: Adds retry logic for gateway failures
6. Commit 412637b: Improves parsing of monitor output, records errors
7. Commit f8d04a7: Sends raw reasoning to monitor instead of summaries
8. Commit 6d5d3cb: Changes to window-based scoring for long trajectories
9. Commit 4bb80a9: Adds tests for windowing, normalisation and error handling
10. Commit ba3f0fa: Adds dry-run mode and per-deployment alert metrics

Let me go through each commit to find potential issues:

### Commit 6edec94
- README update looks good, adds proper documentation for deployments
- monitor.toml changes seem reasonable (model, token limit, timeout)
- Added deployments config section - looks correct

### Commit d414291
- Prompt v4 looks well-structured with clear categories and scoring rubric
- Added tests for prompt loading - good practice
- No obvious issues

### Commit a952492
- Fixed duplicate alerts by selecting only the longest snapshot per episode
- Added proper tests for the new behavior
- No obvious issues

### Commit 806d5c7
- Added batching to reduce memory usage
- Added format_elapsed for better logging
- Tests look good
- No obvious issues

### Commit 38899c7
- Added retry logic for gateway failures
- Good test coverage for retry behavior
- No obvious issues

### Commit 412637b
- Improved parsing of monitor output with strict validation
- Added proper error handling
- Good test coverage
- No obvious issues

### Commit f8d04a7
- Changed to send raw reasoning to the monitor
- Added include_raw_reasoning config option
- Added tests for the new behavior
- No obvious issues

### Commit 6d5d3cb
- Changed to window-based scoring for long trajectories
- Added windowing logic and normalisation
- Updated alert thresholds to [0,1] scale
- Added schema changes to track raw scores and window counts
- Tests look good

### Commit 4bb80a9
- Added comprehensive tests for windowing, normalisation and error handling
- No obvious issues

### Commit ba3f0fa
- Added dry-run mode
- Added per-deployment alert metrics
- Updated documentation
- Added run_metrics table
- Good test coverage

Now, let me look for any potential issues across the entire chain:

1. **Schema Versioning**: I notice that multiple commits are modifying the database schema (adding tables, columns) but there's no schema versioning or migration logic. This could cause problems when upgrading the system, as older databases might not have the new columns/tables.

2. **Error Handling in Windowed Scoring**: In commit 6d5d3cb, when scoring windows concurrently, if one window fails but others succeed, the entire trajectory would fail (due to how exceptions are handled). This seems too strict - we might want to continue with the successfully scored windows.

3. **Deployment Statistics Calculation**: In commit ba3f0fa, the alert_rate is calculated as `stats.alerts / self.scored` but it should be `stats.alerts / stats.scored` (per-deployment rate, not overall rate).

4. **Dry Run Logging**: In the dry run mode, the logging might be confusing because it says "run X (dry run)" but then still reports metrics as if it's a real run. This is mostly cosmetic but could be clearer.

5. **Windowing Logic**: The windowing logic in commit 6d5d3cb includes message 0 (the instructions) in every window after the first. This is good, but I don't see any test specifically checking that message 0 is preserved in all windows.

Let me focus on the most significant issues:

The most critical issue appears to be #3: the alert_rate calculation is incorrect. In `cotmon/pipeline.py`, in the `DeploymentStats` class and in the `finalise` method of `RunSummary`, the calculation is:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

But it should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a logical error that would make the alert rate for each deployment equal to the overall alert rate, not the per-deployment rate.

Let me also check the windowing logic issue. Looking at the tests in `tests/test_windows.py`, there is a test `test_later_windows_start_with_instructions` that checks if message 0 is in all windows, so that's covered.

For the schema versioning issue, it's more of a design concern that might not be critical for this immediate review, but it's worth noting.

Let me also check if there are any other issues:

In `cotmon/scoring.py`, in the `score_trajectory` function, the rationale is set to the rationale of the worst (highest score) window. This seems correct from a safety perspective (taking the most concerning assessment), but I don't see any test specifically checking this behavior.

Actually, there is a test in `tests/test_scoring.py` called `test_trajectory_takes_highest_window` that checks the raw score is the highest window score, but it doesn't explicitly check the rationale. It should be fine since it's using the same `worst` object for both, but it's worth noting.

Another issue: In `cotmon/alerts.py`, the `run_metrics` table has a column `alert_rate` defined as `REAL NOT NULL`, but if `stats.scored` is 0, the calculation would be 0.0 (due to the `if self.scored else 0.0`), which is fine. But in the case where no trajectories were scored for a deployment, the rate is 0.0, which is correct.

Wait, I found another issue in the `normalise` function in `cotmon/scoring.py`:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

In `cotmon/parse.py`, we have:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So the normalisation would be:
- 1 -> 0.0
- 10 -> 1.0

But the range is 9 (10-1), not 10. This means the normalisation is correct: (raw-1)/9 maps 1-10 to 0-1.

Actually, let me verify:
- (1-1)/9 = 0/9 = 0.0
- (10-1)/9 = 9/9 = 1.0

This is correct.

The main issue I found is the incorrect calculation of alert_rate in the per-deployment metrics. This is a logical bug that would make the metrics misleading.

Let me also check if there are any other issues:

In `cotmon/reporting.py`, the `write_summary_csv` function writes deployment metrics to a CSV file. It uses:
```python
stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This is fine, but it doesn't include the alert_rate. The docstring says "Write deployment counts to a CSV stream for spreadsheet import" and the header is "deployment,scored,alerts,errors", so it's consistent with what's documented.

However, since alert_rate is calculated but not exported, it might be worth including it in the CSV for completeness. But this is a minor issue and not a bug.

Another issue: In `cotmon/pipeline.py`, in the `run_nightly` function, the `per_deployment` dictionary is populated with `DeploymentStats` objects, but there's no handling for deployments that aren't in the `deployments` config section. This is probably fine as the deployment names come directly from the data.

Let me check if there are any performance issues:

In the windowing logic, when scoring trajectories, it creates a ThreadPoolExecutor for each trajectory. This could lead to excessive thread creation if there are many trajectories. It might be better to have a single executor for the entire run.

Actually, looking at the code in `cotmon/scoring.py`:
```python
with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
    replies = list(pool.map(client.complete, requests))
```

This creates a new executor for each trajectory. If there are many trajectories, this could create many executors, each with potentially many threads. This is inefficient and could lead to resource exhaustion.

A better approach would be to have a single executor for the entire run, but this would require a more significant refactor. Given the scope of this review, I'll focus on the clear bug I found.

So, the main issue to fix is the incorrect alert_rate calculation.

Let me create a follow-up commit that fixes this issue.
