Let me analyze the commit chain to understand what's going on and what I should propose as a follow-up commit.

The commit chain shows a series of changes to a monitoring system called "cotmon" that reviews AI agent trajectories for potential "scheming" behavior. The system has evolved through multiple iterations to improve its accuracy, efficiency, and reliability.

Key changes in the commit chain:

1. Commit 6edec94: Upgraded the monitor model from kestrel-2.5-pro to kestrel-3.1-pro, increased max_output_tokens to 2048, and request_timeout_s to 120. Updated README with more detailed deployment information.

2. Commit d414291: Introduced a new prompt version (v4) with explicit category definitions for scheming behavior to improve consistency.

3. Commit a952492: Fixed duplicate alerts by selecting only the longest snapshot per episode.

4. Commit 806d5c7: Improved memory efficiency by streaming trajectories in batches rather than loading everything at once.

5. Commit 38899c7: Added retry logic for gateway failures with exponential backoff.

6. Commit 412637b: Implemented strict parsing of monitor output and error recording for malformed replies.

7. Commit f8d04a7: Started sending raw reasoning to the monitor instead of summaries, improving recall.

8. Commit 6d5d3cb: Changed to scoring trajectories in overlapping windows rather than truncating long transcripts, and normalized scores to [0,1] range.

9. Commit 4bb80a9: Added tests for windowing, normalization, and error handling.

10. Commit ba3f0fa: Added --dry-run option and per-deployment alert metrics.

Now, as a code reviewer, I need to look for potential bugs or areas for optimization that weren't addressed in these commits.

Looking at the latest commit (ba3f0fa), I notice a few potential issues:

1. In `cotmon/pipeline.py`, the `run_nightly` function now accepts a `dry_run` parameter, but there's a potential issue with how metrics are handled. The `write_metrics` function in `AlertSink` is called even in dry-run mode, but it has a guard clause that returns early if `dry_run` is True. However, the metrics are still calculated and logged, which is fine for reporting, but the code could be clearer.

2. In `cotmon/alerts.py`, the `write_metrics` function doesn't check if the run is a dry run before inserting data, but it does have a guard clause at the beginning. This is correct, but the function signature could be clearer.

3. In `cotmon/reporting.py`, the `write_summary_csv` function writes deployment counts to a CSV file. However, it doesn't include the alert rate in the CSV output, which seems inconsistent with the `run_metrics` table that does store alert_rate.

4. There's a potential issue with how the `alert_rate` is calculated in `DeploymentStats`. It's calculated as `alerts / scored`, but if `scored` is zero, this would cause a division by zero error. The code in `RunSummary.finalise()` does check for this (`stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0`), but it's using `self.scored` (the total across all deployments) rather than `stats.scored` (the count for that specific deployment). This seems incorrect - the alert rate for a specific deployment should be based on that deployment's scored count, not the total.

Let me verify this last point, as it seems like a potential bug:

In `cotmon/pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is calculating the alert rate for each deployment as (deployment alerts) / (total scored across all deployments). This is incorrect. The alert rate for a specific deployment should be (deployment alerts) / (deployment scored).

This is a bug that should be fixed.

Another issue I noticed:
In `cotmon/pipeline.py`, the `run_nightly` function logs per-deployment metrics:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

But as we just identified, `stats.alert_rate` is incorrectly calculated.

Let me also check if there are any other potential issues:

In `cotmon/alerts.py`, the `run_metrics` table is defined with:
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

And in `AlertSink.write_metrics`:
```python
self.conn.executemany(
    "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
        (self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
        for name, s in sorted(per_deployment.items())
    ],
)
```

This is correctly inserting the per-deployment metrics, but the `alert_rate` value being inserted is the incorrect one (based on total scored, not deployment scored).

So the main bug to fix is in how the alert rate is calculated for each deployment.

Let me also check if there are any other potential improvements:

1. The `write_summary_csv` function in `cotmon/reporting.py` doesn't include the alert_rate in the CSV output, which seems inconsistent with the metrics being logged and stored in the database.

2. In `cotmon/pipeline.py`, the `run_nightly` function has a comment that says "With ``dry_run`` the monitor is still called but nothing is written to the store and nobody is paged; the summary is returned as usual." However, in the implementation, if `dry_run` is True, the `AlertSink` is created with `dry_run=True`, which causes `record` and `record_error` to be no-ops. But the monitor is still called, which is correct.

3. In `cotmon/alerts.py`, the `AlertSink` class has a `dry_run` attribute, but it's not used consistently. For example, in `record` and `record_error`, it checks `if self.dry_run: return`, but in `write_metrics`, it has `if self.dry_run: return` at the beginning. This is correct, but the code could be clearer.

Given these observations, the main bug to fix is the calculation of the alert rate for each deployment. It should be based on the deployment's own scored count, not the total across all deployments.

Let me draft a follow-up commit that fixes this issue and potentially addresses the CSV output inconsistency.

The commit should:
1. Fix the alert rate calculation to be per-deployment (alerts/scored for that deployment)
2. Include alert_rate in the CSV output from write_summary_csv for consistency
3. Add a test to verify the correct calculation

Let me check if there's anything else:

Looking at the tests in `tests/test_pipeline.py`, there's a test `test_per_deployment_metrics` that verifies some aspects of the per-deployment metrics, but it doesn't check the alert_rate calculation. We should add a test for that.

Actually, the current test doesn't verify the alert_rate at all, so we should add a test that specifically checks the correct calculation of the alert_rate per deployment.

So the follow-up commit should include:
1. Fix for the alert_rate calculation in RunSummary.finalise()
2. Update to write_summary_csv to include alert_rate
3. Additional test to verify the correct calculation of alert_rate per deployment

Let me write the diff for this commit.

First, the commit message:

```
monitor: fix per-deployment alert rate calculation

The alert rate for each deployment was incorrectly calculated as
(deployment alerts) / (total scored across all deployments). It should be
(deployment alerts) / (deployment scored).

Also includes the alert_rate in the summary CSV for consistency with the
metrics logged and stored in the database.

Adds a test to verify the correct calculation of per-deployment alert rates.
```

Now, the code changes:

1. In cotmon/pipeline.py, change the finalise method:
```python
def finalise(self) -> RunSummary:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
    return self
```

Wait, I notice that `finalise` is currently a void method (returns None). It should probably return self for chaining, but that's not critical. The main issue is the calculation.

Actually, looking again:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

It should be:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

2. In cotmon/reporting.py, update write_summary_csv:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors,alert_rate\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.3f}\n")
```

3. Add a test in tests/test_pipeline.py:
```python
def test_per_deployment_alert_rate(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    # research-agent has 1 alert out of 1 scored (100%)
    # codegen-agent has 0 alerts out of 2 scored (0%)
    backend = FakeBackend(lambda req: "bad\n<score>9</score>" if "research-agent" in req.user else "<score>3</score>")
    summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
    
    research = summary.per_deployment["research-agent"]
    self.assertEqual(research.scored, 1)
    self.assertEqual(research.alerts, 1)
    self.assertEqual(research.alert_rate, 1.0)
    
    codegen = summary.per_deployment["codegen-agent"]
    self.assertEqual(codegen.scored, 2)
    self.assertEqual(codegen.alerts, 0)
    self.assertAlmostEqual(codegen.alert_rate, 0.0)
```

Wait, there's a potential issue with the test. The `FakeBackend` in the existing tests is defined in helpers.py, but I don't see it in the commit chain. Let me check if it's available.

Actually, in the commit chain, there's a test file `tests/test_pipeline.py` that uses `FakeBackend`, so it must be defined somewhere. I'll assume it's available for the test.

Let me double-check the calculation logic one more time to be sure.

For each deployment:
- alert_rate = alerts / scored (for that deployment)
- If scored is 0, alert_rate should be 0.0 (to avoid division by zero)

Yes, that's correct.

Now, let me write the full diff for the follow-up commit.
