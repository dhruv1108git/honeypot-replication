I need to review the commit chain and propose a follow-up commit that fixes any bugs or improves the code.

Let's go through each commit to understand the changes:

1. **commit 6edec94**: Updates monitor to kestrel-3.1-pro, increases max_output_tokens to 2048, and request_timeout to 120s. Also updates README with new deployment info.

2. **commit d414291**: Adds scheming_v4 prompt with explicit category definitions, switches to prompt_version v4.

3. **commit a952492**: Fixes duplicate alerts by selecting only the longest snapshot per episode.

4. **commit 806d5c7**: Adds batch processing for trajectories to reduce memory usage.

5. **commit 38899c7**: Adds retry logic for gateway failures with exponential backoff.

6. **commit 412637b**: Adds strict monitor output parsing and error recording.

7. **commit f8d04a7**: Sends raw reasoning to the monitor instead of summaries.

8. **commit 6d5d3cb**: Scores long trajectories in windows, normalizes scores to [0,1].

9. **commit 4bb80a9**: Adds tests for windowing, normalisation and pipeline error handling.

10. **commit ba3f0fa**: Adds --dry-run option and per-deployment alert metrics.

Now I need to analyze the code for bugs or areas for improvement. Let me focus on the most recent commits as they're most likely to have issues that weren't caught in earlier reviews.

Looking at commit ba3f0fa (the latest one), which adds dry-run functionality and per-deployment metrics:

1. In `cotmon/pipeline.py`, the `run_nightly` function now has a `dry_run` parameter. The implementation looks generally good, but I notice something:

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
            stats = summary.deployment(traj.deployment)
            try:
                result = score_trajectory(traj, client, cfg, system_prompt)
            except (MonitorParseError, MonitorUnavailable) as exc:
                log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
                sink.record_error(traj, exc)
                summary.errors += 1
                stats.errors += 1
                continue
            decision = decide(result.score, cfg)
            sink.record(result, decision)
            flagged = decision in ("alert", "page")
            summary.scored += 1
            summary.alerts += flagged
            summary.pages += decision == "page"
            stats.scored += 1
            stats.alerts += flagged
        sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
    # ...
```

In the dry-run mode, we're still calling `sink.commit()` after each batch, but `sink.record()` and `sink.record_error()` are no-ops in dry-run mode (as they check `self.dry_run` before writing). However, the final `sink.write_metrics()` and `sink.commit()` are also no-ops in dry-run mode because `write_metrics` checks for dry-run.

This seems correct, but let me check the implementation of `AlertSink`:

```python
class AlertSink:
    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
        self.conn = conn
        self.run_id = run_id
        self.pager = pager
        self.dry_run = dry_run
        if not dry_run:
            conn.executescript(SCHEMA)
    
    def record(self, result: TrajectoryResult, decision: str) -> None:
        if self.dry_run:
            return
        # ...
    
    def record_error(self, traj: Trajectory, exc: Exception) -> None:
        if self.dry_run:
            return
        # ...
    
    def write_metrics(self, per_deployment: dict) -> None:
        if self.dry_run:
            return
        # ...
    
    def commit(self) -> None:
        self.conn.commit()
```

The issue I see is that in dry-run mode, `conn.executescript(SCHEMA)` is never called, which means the tables aren't created. This is fine since we're not writing anything, but there's a potential issue:

In the `run_nightly` function, we have:
```python
batches = store.iter_trajectory_batches(conn, since, until, cfg.store.batch_size)
```

This reads from the store. If the store is empty or doesn't have the right schema, this could fail. However, the store schema is created elsewhere (probably in the store module), not in the AlertSink. So this might not be an issue.

Wait, looking at `cotmon/store.py`, I see:
```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id  TEXT PRIMARY KEY,
    episode_id   TEXT NOT NULL,
    deployment   TEXT NOT NULL,
    agent_model  TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    n_messages   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    snapshot_id  TEXT NOT NULL,
    idx          INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    reasoning    TEXT,
    reasoning_summary TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, idx),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
);
"""
```

And there's a `connect` function that probably sets up the schema. So the store schema is independent of the AlertSink, which is good.

Another issue I noticed: In `run_nightly`, we're calling `sink.commit()` after processing each batch, even in dry-run mode. This is unnecessary in dry-run mode since no changes are made to the database. It's not harmful, but it's an extra operation that could be skipped.

Actually, looking more carefully, in dry-run mode, the only database operation is reading the trajectories. There are no writes, so committing is unnecessary. But SQLite might still need to commit to release locks, so it might be fine.

Let me check the `store.iter_trajectory_batches` implementation:

```python
def iter_trajectory_batches(
    conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
) -> Iterator[list[Trajectory]]:
    """Yield the selected trajectories in batches of ``batch_size``.

    Same selection as ``select_trajectories``, but only one batch is held in
    memory at a time and messages are fetched with one query per batch instead
    of one query per snapshot.
    """
    cursor = conn.execute(SELECT_SNAPSHOTS, {"since": since, "until": until})
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        batch = [Trajectory(**dict(row)) for row in rows]
        _attach_messages(conn, batch)
        yield batch
```

This is reading from the database, so in dry-run mode, we're just reading data and not writing anything. The `sink.commit()` calls are for the connection used by the AlertSink, which is the same connection. In dry-run mode, since no writes are happening, committing is not necessary but also not harmful.

Now, looking at the `DeploymentStats` class:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And the `RunSummary.finalise()` method:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

There's a bug here. The alert rate should be `stats.alerts / stats.scored` if `stats.scored` is not zero, not `stats.alerts / self.scored`. The current implementation calculates the deployment's alert rate as a fraction of the total scored trajectories, not the deployment's own scored trajectories.

For example, if we have:
- research-agent: scored=10, alerts=2
- codegen-agent: scored=20, alerts=4
- Total scored=30

The current implementation would calculate:
- research-agent alert_rate = 2/30 = 0.067
- codegen-agent alert_rate = 4/30 = 0.133

But it should be:
- research-agent alert_rate = 2/10 = 0.2
- codegen-agent alert_rate = 4/20 = 0.2

This is definitely a bug that needs to be fixed.

Let me verify this by looking at the test added in commit ba3f0fa:

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

I found another potential issue. In the `run_nightly` function:

```python
for batch in batches:
    for traj in batch:
        stats = summary.deployment(traj.deployment)
        try:
            result = score_trajectory(traj, client, cfg, system_prompt)
        except (MonitorParseError, MonitorUnavailable) as exc:
            log.error("monitor failed on %s: %s", traj.snapshot_id, exc)
            sink.record_error(traj, exc)
            summary.errors += 1
            stats.errors += 1
            continue
        decision = decide(result.score, cfg)
        sink.record(result, decision)
        flagged = decision in ("alert", "page")
        summary.scored += 1
        summary.alerts += flagged
        summary.pages += decision == "page"
        stats.scored += 1
        stats.alerts += flagged
    sink.commit()
```

When there's an error (MonitorParseError or MonitorUnavailable), we increment `summary.errors` and `stats.errors`, but we don't increment `summary.scored` or `stats.scored`. This is correct because an error means the trajectory wasn't scored.

However, in the finalization step:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

The `alert_rate` is calculated as `stats.alerts / self.scored`, but `self.scored` is the total number of successfully scored trajectories, not the total number of trajectories attempted. The total number of trajectories attempted would be `self.scored + self.errors`.

But typically, alert rate is calculated as alerts / scored, not alerts / attempted, so this might be intentional. However, the variable name `alert_rate` suggests it's alerts / scored, which is correct.

Wait, no, the bug is that it's using `self.scored` (total scored across all deployments) instead of `stats.scored` (scored for this deployment).

Let me double-check the code:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, it should be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is clearly a bug.

Another issue I noticed: In `cotmon/reporting.py`, the `write_summary_csv` function:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

It's not including the alert_rate in the CSV. The docstring says "deployment counts", so maybe that's intentional. But the commit message says "per-deployment alert metrics", which might include the rate. However, the rate can be calculated from the other values, so it might be fine to omit it.

Actually, looking at the commit message for ba3f0fa: "Each run now records scored/alerts/errors and the alert rate per deployment in a new run_metrics table". So the rate is stored in the database, but for the CSV export, it might be sufficient to just have the raw counts.

I think the main bug is the incorrect calculation of alert_rate.

Let me check if there are any other issues...

In `cotmon/alerts.py`, the `run_metrics` table definition:

```python
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

This is using the incorrectly calculated `s.alert_rate` (which is alerts / total_scored instead of alerts / deployment_scored).

So the bug affects both the in-memory stats and the database records.

This is a significant bug that needs to be fixed.

Let me see if there are any other issues...

I think that's the main one. There might be other minor issues, but this is the most critical one to fix.

So my follow-up commit should fix the calculation of `alert_rate` in `RunSummary.finalise()`.

The fix is simple:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

I should also update the test to check the alert_rate value to catch this bug in the future.

Let me look at the test `test_per_deployment_metrics`:

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

I should add a check for the alert_rate:

```python
def test_per_deployment_metrics(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="codegen-agent"),
        make_snapshot("s3", "ep3", 6, deployment="research-agent"),  # Add another research-agent snapshot
    )
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual(set(summary.per_deployment), {"research-agent", "codegen-agent"})
    
    # research-agent has 2 scored, 2 alerts -> alert_rate = 1.0
    # codegen-agent has 1 scored, 1 alert -> alert_rate = 1.0
    research = summary.per_deployment["research-agent"]
    codegen = summary.per_deployment["codegen-agent"]
    self.assertEqual(research.scored, 2)
    self.assertEqual(research.alerts, 2)
    self.assertEqual(research.alert_rate, 1.0)
    self.assertEqual(codegen.scored, 1)
    self.assertEqual(codegen.alerts, 1)
    self.assertEqual(codegen.alert_rate, 1.0)
    
    self.assertEqual(len(rows(conn, "run_metrics")), 2)
    # We could also check the values in run_metrics
```

But since I'm only proposing a single follow-up commit, I'll focus on fixing the bug and not necessarily adding the test (though it would be good to have).

Actually, as a code reviewer, I should propose a fix that includes a test to verify the fix. So I'll include a test update in my commit.

Let me check if there's a test file where I can add this check. The test `test_per_deployment_metrics` is in `tests/test_pipeline.py`, so I'll update that test.

Wait, the test as written wouldn't actually test the alert_rate calculation correctly because it only has one trajectory per deployment, and it's an alert, so the rate would be 1.0 in both cases. I need to add a non-alert trajectory to test a rate less than 1.0.

Actually, the FakeBackend in the test always returns a score of 9, which is a page, so it's always an alert. To test a rate less than 1.0, I'd need a mix of alerts and non-alerts.

But for the purpose of verifying the calculation is using the correct denominator, even a rate of 1.0 is sufficient. If the calculation was wrong, it would show a different value.

For example, with:
- research-agent: 2 scored, 2 alerts
- codegen-agent: 1 scored, 1 alert
- Total scored: 3

If the calculation was wrong (using total scored as denominator), the rates would be:
- research-agent: 2/3 = 0.666...
- codegen-agent: 1/3 = 0.333...

But with the correct calculation, they should both be 1.0.

So the test as I outlined would catch the bug.

Now, let's write the commit:

Subject: fix: correct alert rate calculation per deployment

Body:
The alert rate for each deployment was incorrectly calculated as
`alerts / total_scored` instead of `alerts / deployment_scored`.
This meant the rate reflected the proportion of total alerts from
that deployment, not the deployment's own alert rate.

Update the calculation to use the deployment's scored count as the
denominator. Also improve the test to verify the correct calculation.

This fixes a bug introduced in commit ba3f0fa where per-deployment
metrics were added.

Now, for the diff. I need to modify:
1. `cotmon/pipeline.py` - fix the `finalise` method
2. `tests/test_pipeline.py` - improve the test to check alert_rate

Let me write the diff.
