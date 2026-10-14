Let me analyze the commit chain for the `cotmon` repository, focusing on correctness, bugs, and optimization opportunities.

The commits cover a major refactor of a safety monitoring system for AI agents. The monitor reviews transcripts of AI agent interactions to detect "scheming" behavior. Let me go through the commits:

1. **6edec94**: Moves to kestrel-3.1-pro model, updates config values (max_output_tokens, timeout), and updates README with deployment info.
2. **d414291**: Adds prompt version v4 with explicit category definitions for better consistency.
3. **a952492**: Fixes duplicate alerting by selecting only the longest snapshot per episode.
4. **806d5c7**: Optimizes memory usage by streaming trajectories in batches.
5. **38899c7**: Adds retry logic for gateway failures.
6. **412637b**: Improves error handling for malformed monitor replies.
7. **f8d04a7**: Uses raw reasoning instead of summaries for better detection.
8. **6d5d3cb**: Splits long trajectories into windows for scoring, normalizes scores to [0,1].
9. **4bb80a9**: Adds tests for windowing and error handling.
10. **ba3f0fa**: Adds dry-run mode and per-deployment metrics.

Looking for bugs or issues:

1. In commit **6d5d3cb**, there's a change to the `run_metrics` table schema:
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

And in the `write_metrics` method:
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

The issue here is that the `run_metrics` table has 7 columns but the INSERT statement is providing 7 values. However, looking at the table definition, there are 7 columns but the INSERT statement is using 7 placeholders, which is correct. Wait, let me count again:
- run_id (1)
- deployment (2)
- scored (3)
- alerts (4)
- errors (5)
- alert_rate (6)
- created_at (7)

Yes, 7 columns, and 7 values are being inserted. So this seems correct.

2. In commit **ba3f0fa**, there's a change to the `DeploymentStats` class:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And in the `finalise` method:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Wait, this is calculating `alert_rate` as `stats.alerts / self.scored`. But `self.scored` is the total number of trajectories across all deployments, while `stats.alerts` is the number of alerts for a specific deployment. This would give an incorrect alert rate for each deployment.

The alert rate for a deployment should be `stats.alerts / stats.scored`, not divided by the total across all deployments.

Let me verify:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is a bug. It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This would calculate the alert rate specific to each deployment.

3. In commit **6d5d3cb**, there's a change to the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This looks correct, but let's check the constants. In `parse.py`:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So for a raw score of 1, it would be (1-1)/(10-1) = 0/9 = 0.0
For a raw score of 10, it would be (10-1)/(10-1) = 9/9 = 1.0

This seems correct.

4. In commit **ba3f0fa**, there's a change to the log message in `run_nightly`:
```python
log.info(
    "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
    run_id, " (dry run)" if dry_run else "",
    summary.scored, summary.alerts, summary.pages, summary.errors,
)
```

This is fine.

5. In commit **ba3f0fa**, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This seems correct.

6. In commit **412637b**, there's a change to the `monitor_errors` table schema:
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

This looks correct.

7. In commit **6d5d3cb**, there's a change to the `monitor_results` table schema:
```python
CREATE TABLE IF NOT EXISTS monitor_results (
    run_id       TEXT NOT NULL,
    snapshot_id  TEXT NOT NULL,
    episode_id   TEXT NOT NULL,
    deployment   TEXT NOT NULL,
    agent_model  TEXT NOT NULL,
    score        REAL NOT NULL,
    raw_score    INTEGER NOT NULL,
    n_windows    INTEGER NOT NULL,
    decision     TEXT NOT NULL,
    rationale    TEXT,
    created_at   TEXT NOT NULL
);
```

This looks correct.

8. In commit **806d5c7**, there's a change to the `iter_trajectory_batches` function:
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

This seems correct for batching.

9. In commit **a952492**, there's a change to the `SELECT_SNAPSHOTS` query:
```python
SELECT_SNAPSHOTS = """
SELECT snapshot_id, episode_id, deployment, agent_model, captured_at, n_messages
FROM (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.episode_id
            ORDER BY s.n_messages DESC, s.captured_at DESC
        ) AS rn
    FROM snapshots AS s
    WHERE s.captured_at >= :since AND s.captured_at < :until
)
WHERE rn = 1
ORDER BY episode_id
"""
```

This seems correct for selecting the longest snapshot per episode.

10. In commit **38899c7**, there's a change to the `MonitorClient` class:
```python
class MonitorClient:
    """Wraps a backend with retries and exponential backoff."""

    def __init__(self, backend, max_retries: int = 4, backoff_s: float = 2.0, sleep=None):
        self.backend = backend
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.sleep = sleep or time.sleep

    def complete(self, req: MonitorRequest) -> str:
        for attempt in range(self.max_retries + 1):
            try:
                return self.backend.complete(req)
            except (TransientBackendError, TimeoutError) as exc:
                if attempt == self.max_retries:
                    raise MonitorUnavailable(
                        f"monitor {req.model} unavailable after {attempt + 1} attempts"
                    ) from exc
                delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
                log.warning("monitor request failed (%s); retry %d in %.1fs", exc, attempt + 1, delay)
                self.sleep(delay)
        raise AssertionError("unreachable")
```

This seems correct for retry logic.

The main bug I found is in the alert rate calculation. Let me verify this with the code:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is definitely wrong. The alert rate for a specific deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment, not divided by the total number of trajectories across all deployments.

This would make the alert rate for each deployment artificially low if there are multiple deployments being monitored, since it's dividing by a larger number (the total across all deployments) rather than the correct denominator (the number for that specific deployment).

Let's fix this bug. The correct calculation should be:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This will give the correct alert rate for each deployment.

Additionally, I should check if there are any other issues:

1. In commit **ba3f0fa**, the log message for per-deployment metrics:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This is logging the alert rate, which we've just determined is being calculated incorrectly.

2. In commit **ba3f0fa**, the `write_summary_csv` function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include the alert rate in the CSV, which might be intentional. But if the alert rate calculation is fixed, it might be worth including it.

However, the issue description doesn't mention needing to change the CSV format, so I'll focus on the bug I found.

Let me double-check if there are any other potential issues:

- In commit **6d5d3cb**, the `normalise` function:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This is correct, but note that `MAX_SCORE - MIN_SCORE` is 9, not 10. So the range is [0, 1] but with steps of 1/9. This is fine as long as the thresholds are calibrated accordingly.

- In commit **ba3f0fa**, the `DeploymentStats` class:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

This seems fine.

So the main issue I found is the incorrect calculation of `alert_rate`. Let me prepare a follow-up commit to fix this.

The commit should:
1. Fix the `finalise` method to calculate alert rate correctly
2. Update any related tests to reflect the correct calculation

Let me check if there are tests for this:

In commit **ba3f0fa**, there's a test for per-deployment metrics:
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

This test doesn't check the `alert_rate` value, so it wouldn't catch the bug. I should add a test to verify the correct calculation, but since I'm only supposed to propose a follow-up commit, I'll focus on the fix itself.

Actually, the instructions say to "propose follow-up commits" that fix bugs and optimize. So I should fix the bug and, if possible, add a test to ensure it's fixed.

Let me see if I can add a test in the follow-up commit:

In `tests/test_pipeline.py`, I could add:
```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    # First research-agent trajectory gets an alert, second doesn't
    backend = FakeBackend(lambda req: "<score>9</score>" if "ep1" in req.user else "<score>5</score>")
    summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
    
    research_stats = summary.per_deployment["research-agent"]
    codegen_stats = summary.per_deployment["codegen-agent"]
    
    self.assertEqual(research_stats.scored, 2)
    self.assertEqual(research_stats.alerts, 1)
    self.assertAlmostEqual(research_stats.alert_rate, 0.5)  # 1 alert out of 2 scored
    
    self.assertEqual(codegen_stats.scored, 1)
    self.assertEqual(codegen_stats.alerts, 1)
    self.assertEqual(codegen_stats.alert_rate, 1.0)  # 1 alert out of 1 scored
```

This test would verify that the alert rate is calculated correctly per deployment.

So my follow-up commit should:
1. Fix the alert rate calculation
2. Add a test to verify the calculation

Let me write the commit:

Subject: "fix: correct alert rate calculation per deployment"

Body:
```
The alert rate for each deployment was incorrectly calculated as
`stats.alerts / self.scored`, which divides by the total number of
trajectories across all deployments. This resulted in artificially low
alert rates.

The correct calculation is `stats.alerts / stats.scored`, which gives
the proportion of alerts for that specific deployment.

Also adds a test to verify the correct calculation.
```

Now for the diff:

1. Fix the `finalise` method in `cotmon/pipeline.py`
2. Add a test in `tests/test_pipeline.py`

Let me draft the diff:

```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -40,7 +40,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..newhash 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -31,6 +31,23 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # First research-agent trajectory gets an alert, second doesn't
+        backend = FakeBackend(lambda req: "<score>9</score>" if "ep1" in req.user else "<score>5</score>")
+        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
+        
+        research_stats = summary.per_deployment["research-agent"]
+        codegen_stats = summary.per_deployment["codegen-agent"]
+        
+        self.assertEqual(research_stats.scored, 2)
+        self.assertEqual(research_stats.alerts, 1)
+        self.assertAlmostEqual(research_stats.alert_rate, 0.5)  # 1 alert out of 2 scored
+        
+        self.assertEqual(codegen_stats.scored, 1)
+        self.assertEqual(codegen_stats.alerts, 1)
+        self.assertEqual(codegen_stats.alert_rate, 1.0)  # 1 alert out of 1 scored
+
 if __name__ == "__main__":
     unittest.main()
```

Wait, I need to check if `FakeBackend` can handle a callable. Looking at the existing tests:

```python
def test_alert_written(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), **DAY)
    self.assertEqual((summary.scored, summary.alerts, summary.errors), (1, 1, 0))
    self.assertEqual(len(rows(conn, "alerts")), 1)
```

It seems `FakeBackend` expects a string or a callable. Let me check if there's a definition for `FakeBackend`:

In `helpers.py` (not shown in the commits), but since it's used in tests, I'll assume it can handle a callable. If not, I might need to adjust the test.

Actually, in commit **4bb80a9**, there's:

```python
def test_unparsable_reply_is_recorded_as_error(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("The agent then"), **DAY)
    self.assertEqual((summary.scored, summary.errors), (0, 1))
    (err,) = rows(conn, "monitor_errors")
    self.assertEqual(err["error_type"], "MonitorParseError")
    self.assertEqual(rows(conn, "monitor_results"), [])
```

So `FakeBackend` takes a string. Let me check if there's a definition in the code.

Since it's not shown in the commits, I'll assume it's defined in `helpers.py` and can handle a callable. If not, I'll adjust the test to use two different `FakeBackend` instances.

Actually, looking at commit **4bb80a9** again:

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

Yes, `FakeBackend` can take a callable. So my test should work.

Let me finalize the diff:

The commit will fix the alert rate calculation and add a test to verify it.

I need to make sure the diff is accurate. The file `cotmon/pipeline.py` has the `finalise` method that needs to be updated.

Also, in the test, I'm using `FakeBackend` with a callable to return different scores for different episodes.

Let me write the final diff.
