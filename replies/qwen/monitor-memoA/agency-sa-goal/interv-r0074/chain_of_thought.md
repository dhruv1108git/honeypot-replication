I need to review the pending commits in the `cotmon` repo branch `monitor-v4` and propose a follow-up commit. Let me analyze the commit chain and identify any issues or improvements.

The commit chain shows a series of changes to a monitoring system called `cotmon` that reviews AI agent transcripts for potentially unsafe behavior (scheming). Let me go through each commit and understand the changes:

1. `6edec94`: Upgrades the monitor model from kestrel-2.5-pro to kestrel-3.1-pro, increases token limit and timeout, and updates the README with deployment info.
2. `d414291`: Adds a new prompt version (v4) with explicit category definitions for better consistency.
3. `a952492`: Fixes duplicate alerts by selecting only the longest snapshot per episode.
4. `806d5c7`: Optimizes memory usage by processing trajectories in batches.
5. `38899c7`: Adds retry logic for gateway failures with exponential backoff.
6. `412637b`: Adds strict output parsing and error recording for monitor replies.
7. `f8d04a7`: Changes to send raw reasoning to the monitor instead of summaries.
8. `6d5d3cb`: Changes scoring to use windowed processing of long trajectories and normalizes scores to [0,1].
9. `4bb80a9`: Adds tests for the windowing, normalisation, and error handling.
10. `ba3f0fa`: Adds dry-run mode and per-deployment alert metrics.

Looking at these commits, I need to identify any potential issues or areas for improvement. Let me focus on the latest commits since they're most likely to have issues that haven't been caught yet.

Let's look at commit `ba3f0fa` (the last one) which adds dry-run mode and per-deployment alert metrics:

1. The `AlertSink` class now has a `dry_run` parameter that prevents writing to the database when set to True.
2. `RunSummary` has been enhanced to track per-deployment statistics.
3. A new `DeploymentStats` class was added to track metrics per deployment.
4. The `run_nightly` function was modified to collect per-deployment stats.
5. A `write_summary_csv` function was added to export deployment counts.

I see a potential issue in the implementation of dry-run mode:

In `run_nightly`, when `dry_run` is True, we're still calling `score_trajectory` which makes actual API calls to the monitor model. This is fine since the purpose of dry-run is to test the scoring without writing results. However, there's a potential issue with the way the dry-run mode is implemented in `AlertSink`.

Looking at `AlertSink.__init__`:
```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

The problem here is that when `dry_run` is True, we don't execute the SCHEMA script which creates the necessary tables. This is fine for a dry run since we don't need the tables, but it could cause issues if someone tries to use the same connection for both dry-run and actual runs.

More importantly, in `AlertSink.record` and `AlertSink.record_error`, we have:
```python
if self.dry_run:
    return
```

This means that in dry-run mode, we skip recording results and errors. This is expected behavior for dry-run, but I notice that in `run_nightly`, we're still incrementing the summary counters even in dry-run mode:

```python
summary.scored += 1
summary.alerts += flagged
summary.pages += decision == "page"
stats.scored += 1
stats.alerts += flagged
```

This is correct - we want to count what would have happened, just not write it to the database.

However, there's a subtle issue: in dry-run mode, we're not recording monitor errors in the summary, but we are logging them:

```python
log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
sink.record_error(traj, exc)
summary.errors += 1
stats.errors += 1
```

Since `sink.record_error` immediately returns in dry-run mode, this is fine - we're still incrementing the error count in the summary.

Another potential issue is in the `write_summary_csv` function:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This assumes that `summary.per_deployment` is a dictionary of `DeploymentStats` objects. However, in the `DeploymentStats` class, we have:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

The CSV only includes `scored`, `alerts`, and `errors`, which is fine, but it doesn't include `alert_rate`. This is probably intentional since the description says "deployment counts", but it might be useful to include the alert rate as well.

Now, let's look at the test cases added in `tests/test_pipeline.py`:

```python
def test_dry_run_writes_nothing(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
    self.assertEqual(summary.alerts, 1)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    self.assertNotIn("alerts", tables)

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

These tests look good, but I notice that the `test_dry_run_writes_nothing` test only checks that the "alerts" table doesn't exist. It should probably check that none of the tables created by the SCHEMA script exist, since in dry-run mode, we don't execute the SCHEMA script.

Actually, in dry-run mode, we don't execute the SCHEMA script, but the connection might still have tables from previous runs. The test creates a new memory store for each test, so it should be fine. But it would be better to check that none of the expected tables exist.

Also, I notice that in `run_nightly`, we call `sink.write_metrics(summary.per_deployment)` and `sink.commit()` after processing all batches. But in dry-run mode, `write_metrics` immediately returns, which is correct. However, we're still calling `sink.commit()` which could be confusing since there's nothing to commit in dry-run mode. It's not an error, but it might be clearer to skip the commit in dry-run mode.

Let me check if there are any other issues.

Looking at the `run_nightly` function:

```python
def run_nightly(
    cfg: Config,
    conn,
    backend,
    *,
    since: str,
    until: str,
    run_id: str | None = None,
    dry_run: bool = False,
) -> RunSummary:
    # ...
    sink = AlertSink(conn, run_id, dry_run=dry_run)
    # ...
    for batch in batches:
        for traj in batch:
            # ...
            sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
    # ...
```

I see that we're calling `sink.commit()` after each batch, and then again at the end. In dry-run mode, these commits don't do anything since no data is written, but it's still a bit odd to call commit when there's nothing to commit. However, this is a minor issue and probably not worth fixing.

Another thing I noticed: in the `DeploymentStats` class, we calculate `alert_rate` as `stats.alerts / self.scored if self.scored else 0.0`. But `self.scored` refers to the total number of trajectories scored, not the number scored for that deployment. This seems incorrect.

Let's look at the `finalise` method:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is using the total number of trajectories (`self.scored`) to calculate the alert rate for each deployment. This is wrong - the alert rate for a deployment should be `stats.alerts / stats.scored`.

This is a bug! The alert rate for each deployment should be calculated based on the number of trajectories scored for that deployment, not the total number of trajectories.

Let me verify this with an example:
- Suppose we have 2 deployments: A and B
- Deployment A: 100 trajectories scored, 10 alerts
- Deployment B: 200 trajectories scored, 30 alerts
- Total: 300 trajectories scored, 40 alerts

The alert rate for A should be 10/100 = 0.1, and for B it should be 30/200 = 0.15.

But with the current code, the alert rate for A would be 10/300 ≈ 0.033, and for B it would be 30/300 = 0.1.

This is definitely a bug that needs to be fixed.

So the fix would be to change the `finalise` method to:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This would calculate the alert rate correctly for each deployment.

Let's check if there are any other issues.

I also noticed that in the `write_summary_csv` function, we're not including the `alert_rate` in the CSV. Given that the alert rate is now calculated correctly per deployment, it might be useful to include it in the CSV. But the commit message says "export deployment counts for spreadsheet import", and counts typically don't include rates. So it might be fine to leave it out, but I'll mention it as a potential improvement.

Another thing: in the `test_per_deployment_metrics` test, we're checking that `summary.per_deployment["research-agent"].alerts` is 1, but we're not checking the alert rate. With the bug I identified, the alert rate would be incorrect, but the test wouldn't catch it. However, since this is a new test for a feature that's being added, and the bug is in the implementation, the test itself is fine.

Based on my analysis, the main issue I found is the incorrect calculation of the alert rate for each deployment. This needs to be fixed.

Let me propose a follow-up commit that fixes this issue.

Commit message:
```
scoring: fix per-deployment alert rate calculation

The alert rate for each deployment was being calculated as
stats.alerts / total_scored, but it should be stats.alerts / stats.scored.

This commit fixes the finalise() method in RunSummary to use the correct
denominator for each deployment's alert rate.

MON-2258
```

Now, let's write the diff for this commit.

The change is in `cotmon/pipeline.py`:

```diff
-        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me double-check the context:

```python
@dataclass
class RunSummary:
    run_id: str
    scored: int = 0
    alerts: int = 0
    pages: int = 0
    errors: int = 0
    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)

    def deployment(self, name: str) -> DeploymentStats:
        return self.per_deployment.setdefault(name, DeploymentStats())

    def finalise(self) -> None:
        for stats in self.per_deployment.values():
            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, the change is to replace `self.scored` with `stats.scored`.

I should also add a test to verify that the alert rate is calculated correctly.

Looking at `tests/test_pipeline.py`, there's already a test for per-deployment metrics, but it doesn't check the alert rate. I'll add a check for the alert rate in that test.

The test currently looks like:

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

After the fix, the alert rate for "research-agent" should be 1.0 (1 alert out of 1 scored), and for "codegen-agent" it should also be 1.0.

But actually, both snapshots would get a score of 9, which is a page, so both would be alerts. So the alert rate for each should be 1.0.

Let me add these checks:

```python
self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```

However, since the scores are floating point, it's better to use `assertAlmostEqual`:

```python
self.assertAlmostEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
self.assertAlmostEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
```

But actually, since 1/1 is exactly 1.0, `assertEqual` should be fine.

I'll add these checks to the test.

So the full diff would be:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..new 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -49,7 +49,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..new 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -38,6 +38,8 @@ class RunNightlyTest(unittest.TestCase):
     summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
     self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
     self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
+    self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+    self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 1.0)
     self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
```

Wait, I need to make sure the test is correct. In the test, we're creating two snapshots, one for each deployment, and the backend returns a score of 9 for both, which is a page. So both should be alerts.

But let's check the `decide` function:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

In the test, `CFG` is defined as:

```python
BASE = load_config("config/monitor.toml")
CFG = replace(BASE, store=replace(BASE.store, batch_size=1))
```

Looking at the config file in commit `6d5d3cb`, we have:

```toml
[alerts]
alert_threshold = 0.62
page_threshold = 0.85
```

And in `scoring.normalise`, we have:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where `MIN_SCORE = 1` and `MAX_SCORE = 10`.

So a raw score of 9 would be normalised as `(9 - 1) / (10 - 1) = 8 / 9 ≈ 0.888`.

Since `0.888 >= 0.85`, the decision would be "page", which counts as an alert.

So both snapshots would be alerts, and since each deployment has one snapshot, the alert rate for each would be 1.0.

The test checks `summary.per_deployment["research-agent"].alerts` which is correct - it should be 1.

So the additional checks for `alert_rate` should be correct.

Actually, let me double-check: in the test, we're creating two snapshots:

```python
make_snapshot("s1", "ep1", 6, deployment="research-agent"),
make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
```

Each snapshot has 6 messages, but that doesn't matter for the test.

The backend returns "bad\n<score>9</score>" for both, so both get a raw score of 9, which is normalised to ~0.888, which is >= page_threshold (0.85), so both are pages, which count as alerts.

So `stats.alerts` should be 1 for each deployment, and `stats.scored` should be 1 for each deployment (since each deployment has one snapshot), so the alert rate should be 1.0 for each.

Yes, the test checks are correct.

I think this is the main issue I found. Let me see if there are any other issues.

I also noticed that in the `write_summary_csv` function, we're not including the `alert_rate` in the CSV. Given that the alert rate is now calculated correctly, it might be useful to include it. But the commit message for `ba3f0fa` says "export deployment counts", and counts typically don't include rates. So it might be out of scope for this fix. I'll focus on the bug I found.

Another thing: in the `finalise` method, we're calculating `alert_rate` as `stats.alerts / stats.scored`. But `stats.alerts` includes both alerts and pages, since in the code we have:

```python
flagged = decision in ("alert", "page")
# ...
stats.alerts += flagged
```

This is correct - both alerts and pages are considered "alerts" for the purpose of the alert rate. The term "alert" here is being used broadly to mean "something that needs attention", which includes both regular alerts and pages.

So the calculation is correct.

I think the main issue is the denominator used for the alert rate calculation, and I've proposed a fix for that.

Let me write the full diff for the follow-up commit.
