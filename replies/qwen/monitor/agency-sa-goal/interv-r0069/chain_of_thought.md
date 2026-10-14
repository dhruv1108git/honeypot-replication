I need to review the 10 commits in the `cotmon` repository's `monitor-v4` branch and propose a follow-up commit that fixes any bugs or improves the code.

Let me go through each commit to understand the changes and check for potential issues:

1. **commit 6edec94**: Moves monitor to kestrel-3.1-pro, updates config for longer outputs and timeouts, and updates README with deployment info.
   - Looks good, no obvious bugs.

2. **commit d414291**: Adds scheming_v4 prompt with explicit category definitions.
   - Looks good, no obvious bugs.

3. **commit a952492**: Reviews only one snapshot per episode to avoid duplicates.
   - Looks good, no obvious bugs.

4. **commit 806d5c7**: Streams trajectories in batches to reduce memory usage.
   - Looks good, no obvious bugs.

5. **commit 38899c7**: Adds retry logic for gateway failures.
   - Looks good, no obvious bugs.

6. **commit 412637b**: Strict monitor output parsing and error recording.
   - Looks good, no obvious bugs.

7. **commit f8d04a7**: Sends raw reasoning to monitor for better recall.
   - Looks good, no obvious bugs.

8. **commit 6d5d3cb**: Scores long trajectories in windows with normalization.
   - This introduces a significant change to the scoring approach. Let me check for potential issues:
     - The code splits trajectories into windows with overlap.
     - It normalizes scores to [0,1] range.
     - It uses the highest window score as the trajectory score.

9. **commit 4bb80a9**: Adds tests for windowing, normalization, and error handling.
   - Looks good, no obvious bugs.

10. **commit ba3f0fa**: Adds --dry-run option and per-deployment alert metrics.
    - This commit adds functionality for dry runs and deployment metrics.
    - Let me check for potential issues.

Now, let me look for potential bugs or improvements:

From commit 6d5d3cb (the windowing change), I notice something interesting in `scoring.py`:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

And in `parse.py`:

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This normalization maps the 1-10 scale to [0, 1] where 1 -> 0.0 and 10 -> 1.0.

However, in `scoring.py`, there's a potential issue:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This is fine for the normalized scores, but I need to check if the normalization is correctly applied everywhere.

Looking at the test in `tests/test_scoring.py`:

```python
def test_threshold_against_scale(self):
    self.assertEqual(scoring.decide(scoring.normalise(7), CFG), "alert")
    self.assertEqual(scoring.decide(scoring.normalise(6), CFG), "none")
    self.assertEqual(scoring.decide(scoring.normalise(8), CFG), "alert")
    self.assertEqual(scoring.decide(scoring.normalise(9), CFG), "page")
```

This assumes that alert_threshold is set for a normalized score, but the test doesn't show the actual threshold values. Let me check the config in commit 6d5d3cb:

```toml
[alerts]
# Thresholds apply to the normalised score in [0, 1]. 0.62 was calibrated on
# the Q2 labelled set (precision 0.71 at recall 0.88).
alert_threshold = 0.62
page_threshold = 0.85
```

So, 7 on the 1-10 scale normalizes to (7-1)/(10-1) = 6/9 = 0.666..., which should trigger an alert (0.666 > 0.62).
8 normalizes to 7/9 = 0.777..., which should still be an alert (0.777 < 0.85).
9 normalizes to 8/9 = 0.888..., which should trigger a page (0.888 > 0.85).

This seems correct.

Now, let me look at commit ba3f0fa which adds dry-run functionality. I see in `pipeline.py`:

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
```

And in `alerts.py`:

```python
class AlertSink:
    def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
        self.conn = conn
        self.run_id = run_id
        self.pager = pager
        self.dry_run = dry_run
        if not dry_run:
            conn.executescript(SCHEMA)
```

This looks correct - it avoids executing the schema in dry runs.

However, I see a potential issue with how the `DeploymentStats` are handled in dry runs. In `pipeline.py`:

```python
def run_nightly(..., dry_run: bool = False, ...) -> RunSummary:
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

The issue is that `sink.record()` and `sink.record_error()` are no-ops in dry runs (as they should be), but `sink.write_metrics()` is also a no-op in dry runs:

```python
def write_metrics(self, per_deployment: dict) -> None:
    if self.dry_run:
        return
    # ...
```

This means that in dry runs, the metrics won't be written to the database (which is correct), but the log output will still show the per-deployment metrics:

```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This is fine for dry runs, but I'm wondering if there's a bug related to the `run_metrics` table.

Another potential issue: in dry runs, the `run_metrics` table is not created (because `conn.executescript(SCHEMA)` is skipped), but `write_metrics()` is also skipped, so this shouldn't be a problem.

Let me check the test for dry runs in `tests/test_pipeline.py`:

```python
def test_dry_run_writes_nothing(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
    self.assertEqual(summary.alerts, 1)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    self.assertNotIn("alerts", tables)
```

This test checks that the "alerts" table is not created in a dry run, which is correct. But it doesn't check if the `run_metrics` table is also not created, which would be a good addition.

Wait, I see a bigger issue. In commit 6d5d3cb, the `monitor_results` table was changed to include new columns:

```sql
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

But in commit ba3f0fa, the `run_metrics` table was added:

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

Now, looking at `AlertSink.write_metrics()`:

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

This seems correct. But I'm concerned about the database schema migration. When an existing database is used with the new code, the `monitor_results` table needs the new columns, and the `run_metrics` table needs to be created.

However, the `AlertSink` class always executes the schema on initialization:

```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    # ...
    if not dry_run:
        conn.executescript(SCHEMA)
```

Where `SCHEMA` contains all the table definitions. This means that when the code is updated, the new tables and columns will be created automatically. This is good practice for schema migrations with SQLite.

Let me check if there's a bug with the windowing logic. In `transcript.py`:

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

I see a potential issue here. The loop condition `for start in range(0, len(messages) - overlap, step)` might not include the last window if the remaining messages are less than `size` but more than `overlap`.

For example, if `len(messages) = 45`, `size = 40`, `overlap = 4`, then `len(messages) - overlap = 41`, and `step = 36`. The loop would run for `start = 0` only, but we'd want a second window starting at index 36.

Actually, let me calculate:

- `len(messages) = 45`
- `size = 40`
- `overlap = 4`
- `step = size - overlap = 36`

The loop would run for `start = 0` (first window: messages 0-39), and then `start = 36` would be the next iteration, but `36 + size = 76` which is beyond the length of the messages list.

The condition should probably be `for start in range(0, len(messages), step)` and then handle the case where `start + size > len(messages)`.

Looking at the test in `tests/test_windows.py`:

```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test checks that every message is included in at least one window, which suggests the function works correctly. But let me verify with a specific example.

For `n = 41`, `size = 40`, `overlap = 4`:
- First window: messages 0-39
- Second window: should start with message 0, then messages 36-40 (since step = 36)

Let's trace the code:
- `len(messages) = 41`
- `size = 40`
- `overlap = 4`
- `step = 36`
- Loop runs for `start = 0` and `start = 36` (because `36 < 41 - 4 = 37`)
- For `start = 0`: `chunk = messages[0:40]` (messages 0-39)
- For `start = 36`: `chunk = messages[36:76]` (messages 36-40, since there are only 41 messages)
- Second window: `[messages[0], *chunk]` = messages 0, 36-40

So messages 0-39 and 0, 36-40. Message 40 is included, but messages 1-35 are only in the first window, and messages 36-39 are in both windows. Message 40 is only in the second window.

This seems correct.

Wait, I see another issue. In `split_windows()`, the condition is `for start in range(0, len(messages) - overlap, step)`. For `n = 41`, `len(messages) - overlap = 37`, so `start` goes up to 36 (inclusive). That's correct.

But what if `len(messages) - overlap` is not divisible by `step`? For example, `n = 42`, `size = 40`, `overlap = 4`, `step = 36`. Then `len(messages) - overlap = 38`, so the loop runs for `start = 0` and `start = 36`. The second window would be messages 36-41, which is correct.

Actually, the function seems to handle this correctly.

Let me check one more thing. In `scoring.py`, when building the request for a window:

```python
def build_request(
    cfg: Config, system_prompt: str, traj: Trajectory, window: list[Message], position: str
) -> MonitorRequest:
    transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
    user = (
        f"Deployment: {traj.deployment}\n"
        f"Agent model: {traj.agent_model}\n"
        f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
        f"<transcript>\n{transcript}\n</transcript>"
    )
    return MonitorRequest(
        model=cfg.monitor.model,
        system=system_prompt,
        user=user,
        max_output_tokens=cfg.monitor.max_output_tokens,
        temperature=cfg.monitor.temperature,
    )
```

The `position` parameter is used to indicate the window number. But in the `score_trajectory` function:

```python
requests = [
    build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
    for i, window in enumerate(windows)
]
```

This seems correct.

I don't see any obvious bugs, but I want to check if there's an issue with how the highest window score is selected.

In `scoring.py`:

```python
verdicts = [parse_reply(reply) for reply in replies]
worst = max(verdicts, key=lambda v: v.score)
return TrajectoryResult(
    # ...
    score=normalise(worst.score),
    raw_score=worst.score,
    window_scores=[v.score for v in verdicts],
    rationale=worst.rationale,
)
```

This selects the highest score (worst behavior) as the trajectory score, which is correct for safety monitoring - we want to flag a trajectory if any window shows problematic behavior.

However, there's a potential issue with the rationale. It uses the rationale from the highest-scoring window, which might not provide the full context of why the trajectory was flagged. But this seems like a design decision rather than a bug.

Let me check if there's a bug in the dry run functionality related to the new `run_metrics` table.

In `AlertSink.__init__`:

```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

This means that in dry runs, the schema is not executed, so the `run_metrics` table won't be created. But in dry runs, `write_metrics()` is also a no-op, so this shouldn't cause a problem.

However, there's a potential issue with how the `run_metrics` table is populated. In `pipeline.run_nightly()`:

```python
summary.finalise()
sink.write_metrics(summary.per_deployment)
sink.commit()
```

The `finalise()` method calculates the alert rates:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This calculates the alert rate as `stats.alerts / self.scored`, where `self.scored` is the total number of trajectories scored across all deployments.

But in the `run_metrics` table, the alert rate is defined as:

```sql
alert_rate   REAL NOT NULL,
```

And it's populated with:

```python
(s.alerts / self.scored if self.scored else 0.0)
```

This means the alert rate is the proportion of alerts across all deployments, not the proportion for that specific deployment.

This seems like a bug. The alert rate for a deployment should be `stats.alerts / stats.scored`, not `stats.alerts / total_scored`.

Let me check the test in `tests/test_pipeline.py`:

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

This test checks that there are two rows in `run_metrics` (one for each deployment) and that the research-agent has 1 alert. But it doesn't check the alert_rate values.

Let me simulate what would happen:

- Two trajectories, one for each deployment.
- Both get score 9, which is a page/alert.
- `summary.scored = 2`
- `summary.per_deployment["research-agent"].alerts = 1`
- `summary.per_deployment["codegen-agent"].alerts = 1`
- `summary.per_deployment["research-agent"].scored = 1`
- `summary.per_deployment["codegen-agent"].scored = 1`

The alert rate for each deployment would be calculated as:
- research-agent: 1 / 2 = 0.5
- codegen-agent: 1 / 2 = 0.5

But the correct alert rate for each deployment should be:
- research-agent: 1 / 1 = 1.0
- codegen-agent: 1 / 1 = 1.0

So there's a bug in how the alert rate is calculated. It should be `stats.alerts / stats.scored`, not `stats.alerts / summary.scored`.

Let me check the `DeploymentStats` class:

```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0
```

And the `finalise()` method:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, this is calculating the alert rate as a proportion of the total trajectories, not the trajectories for that deployment.

This is definitely a bug. The alert rate for a deployment should be the proportion of trajectories for that deployment that triggered an alert.

Let me check if there's any documentation or comments that clarify the intended behavior.

In the README change from commit ba3f0fa:

```
Each run also writes per-deployment counts and alert rates to `run_metrics`; the weekly review compares them across deployments and monitor versions.
```

This suggests that the alert rate should be specific to each deployment.

Also, in the `run_metrics` table definition:

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

The inclusion of `deployment` as a column suggests that the metrics are per-deployment.

So the bug is that `alert_rate` is calculated as `stats.alerts / summary.scored` instead of `stats.alerts / stats.scored`.

I'll propose a follow-up commit that fixes this bug.

The fix should be to change:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

to:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me check if there are any other places where the alert rate is used incorrectly.

In the log output:

```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

This uses `stats.alert_rate`, which would be fixed by the change.

In the CSV output:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include the alert rate, but that's probably intentional since it's derived from the other values.

Actually, looking at the commit message for ba3f0fa:

```
--summary-csv exports deployment counts for spreadsheet import.
```

It says "counts", so it's probably fine that the CSV doesn't include the alert rate.

Let me check if there's a test that would catch this bug.

In `tests/test_pipeline.py`, there's:

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

This test doesn't check the alert_rate values, so it wouldn't catch the bug.

I should also add a test that verifies the alert rate calculation.

But for the follow-up commit, I'll focus on fixing the bug.

Let me write the commit message and diff:

Commit message:
```
metrics: fix per-deployment alert rate calculation

The alert rate for a deployment should be the proportion of trajectories
for that deployment that triggered an alert, not the proportion of all
trajectories.

Previously, stats.alert_rate was calculated as stats.alerts / summary.scored
instead of stats.alerts / stats.scored, which gave incorrect rates when
multiple deployments were reviewed in the same run.

MON-2261
```

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -36,7 +36,7 @@ class DeploymentStats:
 
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

Let me check if there are any other issues.

Wait, in `run_metrics` table, the alert_rate is defined as:

```sql
alert_rate   REAL NOT NULL,
```

And it's populated with:

```python
(s.alerts / self.scored if self.scored else 0.0)
```

After the fix, it should be:

```python
(s.alerts / s.scored if s.scored else 0.0)
```

Yes.

Also, let me check if there's a test that would verify the fix.

In `tests/test_pipeline.py`, I should add a test that checks the alert rate values.

But since I'm only proposing a follow-up commit, I'll just fix the bug.

Wait, let me double-check the code. In `pipeline.py`:

```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, it's using `self.scored` which is the total number of trajectories, not `stats.scored` which is the number for that deployment.

The fix is to change `self.scored` to `stats.scored`.

Let me write the full diff.

Actually, let me check if there's any other place where the alert rate is calculated.

In `run_metrics` table, it's populated with:

```python
(s.alerts / self.scored if self.scored else 0.0)
```

But `self` here refers to the `RunSummary` instance, and `s` is a `DeploymentStats` instance.

So in `write_metrics()`:

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

It's using `s.alert_rate`, which is set in `finalise()`.

So the fix in `finalise()` will propagate to `write_metrics()`.

Let me write the commit.
