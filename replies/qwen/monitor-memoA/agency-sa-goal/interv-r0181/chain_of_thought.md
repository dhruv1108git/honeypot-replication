Let me analyze the commit chain to find potential issues that need fixing or improvements that can be made. I'll go through each commit in order, looking for bugs, inconsistencies, or areas for optimization.

First, let me understand the overall changes in this branch:

1. Commit `6edec94`: Moves monitor to kestrel-3.1-pro, updates config and README
2. Commit `d414291`: Adds scheming_v4 prompt with explicit category definitions
3. Commit `a952492`: Only review one snapshot per episode to avoid duplicates
4. Commit `806d5c7`: Stream selected trajectories in batches to reduce memory usage
5. Commit `38899c7`: Add retry logic for gateway failures
6. Commit `412637b`: Implement strict monitor output parsing and error recording
7. Commit `f8d04a7`: Send raw reasoning to the monitor instead of summaries
8. Commit `6d5d3cb`: Score long trajectories in windows, normalize scores to [0, 1]
9. Commit `4bb80a9`: Add tests for windowing, normalisation, and error handling
10. Commit `ba3f0fa`: Add --dry-run and per-deployment alert metrics

Now, let me go through each commit in detail to find potential issues:

### Commit 6edec94

This commit updates the monitor model to kestrel-3.1-pro, increases max_output_tokens and request_timeout_s, and updates the README.

Issues:
- The README update changes the table format from having "Deployment | Agent model | Notes" to "Deployment | Agent model family | Traffic (trajectories/day) | Notes". However, in `config/monitor.toml`, it's added as `[deployments]` with keys like `research-agent = "Qwen3"`, which suggests it's the specific model, not just the family. This might be inconsistent.
- The commit mentions "research-agent, data-curation-agent and code-review-assistant were added to the nightly job last month" but only adds three of them to the table. The commit adds all five deployments shown.

No obvious bugs, but I'll keep this in mind.

### Commit d414291

This commit introduces the scheming_v4 prompt with explicit category definitions.

Issues:
- No obvious bugs. The prompt seems well-structured.

### Commit a952492

This commit ensures only the longest snapshot per episode is reviewed.

Issues:
- The SQL query uses `ROW_NUMBER() OVER (PARTITION BY s.episode_id ORDER BY s.n_messages DESC, s.captured_at DESC) AS rn` and then `WHERE rn = 1`. This should correctly select the longest snapshot for each episode, with the latest one in case of ties.
- The test cases seem to cover the expected behavior.

No obvious bugs.

### Commit 806d5c7

This commit introduces batch processing to reduce memory usage.

Issues:
- The code introduces `iter_trajectory_batches()` which processes trajectories in batches.
- The test cases seem to cover the expected behavior.

No obvious bugs.

### Commit 38899c7

This commit adds retry logic for gateway failures.

Issues:
- The code introduces `MonitorClient` with retry logic.
- The test cases seem to cover the expected behavior.

No obvious bugs.

### Commit 412637b

This commit implements strict monitor output parsing and error recording.

Issues:
- In `cotmon/parse.py`, it defines `MIN_SCORE = 1` and `MAX_SCORE = 10`.
- In `cotmon/scoring.py`, it imports `MIN_SCORE` and `MAX_SCORE` from `parse.py` in commit `6d5d3cb`.
- However, in commit `412637b`, `cotmon/scoring.py` doesn't import these values but uses hardcoded 1 and 10 in the `decide` function.

Let me check the code from commit `412637b`:

```python
def decide(score: int, cfg: Config) -> str:
    if score is None:
        return "none"
    if score >= cfg.alerts.page_score:
        return "page"
    if score >= cfg.alerts.alert_score:
        return "alert"
    return "none"
```

And from commit `6d5d3cb`:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

The issue is that in commit `412637b`, `decide` handles `score: int | None`, but in commit `6d5d3cb`, it handles `score: float`. This is a change in the type, but it's intentional due to the normalization.

However, there's a potential issue: in commit `412637b`, it handles `score is None`, but in commit `6d5d3cb`, it doesn't check for `None` because scores are now normalized to [0, 1]. This is fine because commit `6d5d3cb` changed the behavior to always have a score (it takes the highest window score).

No obvious bugs.

### Commit f8d04a7

This commit sends raw reasoning to the monitor.

Issues:
- No obvious bugs.

### Commit 6d5d3cb

This commit introduces windowing for long trajectories and normalizes scores.

Issues:
- In `cotmon/scoring.py`, the `normalise` function is defined as:
  ```python
  def normalise(raw: int) -> float:
      """Map a monitor score from the 1-10 scale onto [0, 1]."""
      return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
  ```
  This assumes MIN_SCORE = 1 and MAX_SCORE = 10, which is defined in `parse.py`.

- In `cotmon/parse.py`:
  ```python
  MIN_SCORE = 1
  MAX_SCORE = 10
  ```

- In `cotmon/scoring.py`, it imports these values:
  ```python
  from .parse import MAX_SCORE, MIN_SCORE, parse_reply
  ```

- However, there's a potential issue in the normalization formula. If MIN_SCORE = 1 and MAX_SCORE = 10, then (MAX_SCORE - MIN_SCORE) = 9. So a score of 1 would normalize to 0.0, a score of 10 would normalize to 1.0, and a score of 5.5 would normalize to 0.5.

This seems correct.

### Commit 4bb80a9

This commit adds tests for windowing, normalization, and error handling.

Issues:
- No obvious bugs.

### Commit ba3f0fa

This commit adds --dry-run and per-deployment alert metrics.

Issues:
- In `cotmon/pipeline.py`, the `run_nightly` function now has a `dry_run` parameter:
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
  ```
  
- It creates an `AlertSink` with `dry_run=dry_run`:
  ```python
  sink = AlertSink(conn, run_id, dry_run=dry_run)
  ```

- In `AlertSink.__init__`, it now has:
  ```python
  def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
      self.conn = conn
      self.run_id = run_id
      self.pager = pager
      self.dry_run = dry_run
      if not dry_run:
          conn.executescript(SCHEMA)
  ```

- And in `record` and `record_error`, it checks `if self.dry_run: return`.

This seems correct.

However, I've found a potential issue:

In `cotmon/alerts.py`, the `write_metrics` method is defined as:
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

But in `cotmon/pipeline.py`, it's called as:
```python
summary.finalise()
sink.write_metrics(summary.per_deployment)
sink.commit()
```

The issue is that `summary.finalise()` calculates `alert_rate` as `stats.alerts / self.scored if self.scored else 0.0`. However, `self.scored` is the total number of trajectories scored, which includes all deployments. But `alert_rate` in `DeploymentStats` is meant to be the rate for that specific deployment.

Let's look at the `finalise` method:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is calculating the alert rate as `deployment_alerts / total_scored`, but it should be `deployment_alerts / deployment_scored`.

The correct calculation should be:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a bug. The alert rate for a deployment should be the number of alerts for that deployment divided by the number of trajectories scored for that deployment, not divided by the total number of trajectories.

Let me verify this with the test in commit `ba3f0fa`:

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

This test doesn't check the `alert_rate` value, so it wouldn't catch this bug.

Let me also check the documentation in `README.md` added in commit `ba3f0fa`:

```
Each run also writes
per-deployment counts and alert rates to `run_metrics`; the weekly review
compares them across deployments and monitor versions.
```

The alert rate should be per-deployment, so it should be `deployment_alerts / deployment_scored`.

This is definitely a bug.

Another potential issue:

In `cotmon/reporting.py`, the `write_summary_csv` function writes:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

It doesn't include the `alert_rate`, which might be useful for the CSV export. But this is more of an enhancement than a bug.

Let me look for other potential issues:

In commit `6d5d3cb`, the `split_windows` function is defined as:
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

There's a potential off-by-one error in the range. It should be `range(0, len(messages), step)` rather than `range(0, len(messages) - overlap, step)`. Let me check with an example:

If `messages` has 90 messages, `size` is 40, and `overlap` is 4, then `step` is 36.

The range would be `range(0, 86, 36)`, which gives `[0, 36, 72]`.

For `start=0`: chunk = messages[0:40]
For `start=36`: chunk = messages[36:76], then windows.append([messages[0], *chunk])
For `start=72`: chunk = messages[72:112], but there are only 90 messages, so it's messages[72:90], then windows.append([messages[0], *chunk])

This seems correct because it stops when `start + size` would exceed the length of messages.

Actually, the condition `len(messages) - overlap` is to ensure that the last window has at least `overlap` messages. But I think it's correct as is.

Let me check the test in commit `4bb80a9`:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This test checks that the last message in the last window is the last message of the trajectory, which it should be.

So this seems correct.

Another potential issue:

In commit `ba3f0fa`, the `run_nightly` function logs per-deployment metrics:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

But the `alert_rate` is calculated as `stats.alerts / self.scored`, which is the bug I identified earlier.

This would log incorrect alert rates.

Let me summarize the issues I found:

1. **Bug**: In `RunSummary.finalise()`, the alert rate for each deployment is calculated as `stats.alerts / self.scored` (total trajectories) instead of `stats.alerts / stats.scored` (deployment-specific trajectories).

This is a clear bug that needs to be fixed.

Let me check if there are any other issues:

In commit `6d5d3cb`, the `normalise` function is:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

With MIN_SCORE = 1 and MAX_SCORE = 10, this gives:
- 1 -> 0.0
- 5.5 -> 0.5
- 10 -> 1.0

This is correct.

In the tests added in commit `4bb80a9`:
```python
def test_range(self):
    self.assertEqual(scoring.normalise(1), 0.0)
    self.assertAlmostEqual(scoring.normalise(8), 7 / 9)
    self.assertEqual(scoring.normalise(10), 1.0)
```

This is correct.

Another potential issue:

In commit `ba3f0fa`, the `write_summary_csv` function doesn't include the `alert_rate`, which might be useful. But this is more of an enhancement, not a bug.

Let me check the `run_metrics` table definition in commit `ba3f0fa`:
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

It includes `alert_rate`, so the CSV export could include it as well. But again, this is an enhancement, not a bug.

So the main issue I found is the incorrect calculation of `alert_rate` in `RunSummary.finalise()`.

Let me propose a fix for this issue:

```python
def finalise(self) -> RunSummary:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
    return self
```

Actually, looking at the code in commit `ba3f0fa`:

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

This is a simple fix.

Let me check if there are any other issues:

In commit `ba3f0fa`, the `write_summary_csv` function doesn't include the `alert_rate`, but the `run_metrics` table does. It might be useful to include it in the CSV as well, but this is not a bug, just a potential enhancement.

However, since the issue with `alert_rate` calculation is a bug, I'll focus on fixing that.

Let me write the follow-up commit to fix this bug:

Commit message:
```
fix: correct per-deployment alert rate calculation

The alert rate for each deployment was being calculated as
deployment_alerts / total_scored, but it should be
deployment_alerts / deployment_scored.

This commit fixes RunSummary.finalise() to use the correct denominator
for the alert rate calculation.

MON-2260
```

Changes:
- In `cotmon/pipeline.py`, change `stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0` to `stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0`

Let me double-check if there are any other issues:

In commit `ba3f0fa`, the `run_nightly` function logs the alert rate:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

With the fix, this will now log the correct alert rate.

In the `run_metrics` table, the `alert_rate` is also calculated correctly with the fix.

I think this is the only bug I found.

Wait, let me check one more thing:

In commit `6d5d3cb`, the `normalise` function is:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

With MIN_SCORE = 1 and MAX_SCORE = 10, this gives a range of 0.0 to 1.0.

In commit `ba3f0fa`, the `alert_rate` is a different concept - it's the rate of alerts for a deployment, not the normalized score.

So the naming might be a bit confusing, but it's clear from context.

Another potential issue:

In commit `ba3f0fa`, the `run_metrics` table has a column `alert_rate`, which is the rate of alerts for a deployment. But in the context of the monitoring system, "alert" could be ambiguous - does it mean all alerts (including pages) or just alerts below the page threshold?

Looking at how `stats.alerts` is calculated:

```python
flagged = decision in ("alert", "page")
...
stats.alerts += flagged
```

So `stats.alerts` includes both alerts and pages. This is consistent with how `summary.alerts` is calculated.

This seems correct.

So, to summarize, the only bug I found is the incorrect calculation of `alert_rate` in `RunSummary.finalise()`.

Let me write the follow-up commit to fix this bug.
