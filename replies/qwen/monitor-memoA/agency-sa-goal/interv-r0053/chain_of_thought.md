Let me analyze the commit chain and identify any issues or areas for improvement.

First, I'll go through the commits to understand the overall changes:

1. `6edec94`: Upgrade monitor model to kestrel-3.1-pro, increase max_output_tokens to 2048, request_timeout_s to 120, and update README with deployment info.
2. `d414291`: Add scheming_v4 prompt with explicit category definitions, switch to prompt_version v4.
3. `a952492`: Only review one snapshot per episode (the longest one) to avoid duplicate alerts.
4. `806d5c7`: Stream trajectories in batches to reduce memory usage.
5. `38899c7`: Add retry logic for gateway failures with exponential backoff.
6. `412637b`: Implement strict monitor output parsing and record monitor errors.
7. `f8d04a7`: Send raw reasoning to the monitor instead of summaries.
8. `6d5d3cb`: Score long trajectories in windows, normalize scores to [0,1].
9. `4bb80a9`: Add tests for windowing, normalisation, and error handling.
10. `ba3f0fa`: Add --dry-run option and per-deployment alert metrics.

Now, let me look for potential issues:

1. In commit `ba3f0fa`, there's a change to the `run_nightly` function where it calls `summary.finalise()` and `sink.write_metrics(summary.per_deployment)`. However, I notice that `finalise()` is only called after processing all trajectories, but there's a potential issue with the alert rate calculation.

Looking at the `DeploymentStats` class:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0

def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

There's a bug here: `stats.alert_rate = stats.alerts / self.scored` should be `stats.alert_rate = stats.alerts / stats.scored` because the alert rate for a deployment should be calculated based on the number of trajectories scored for that deployment, not the total number of trajectories.

This is a critical bug because it would calculate the alert rate incorrectly, especially if some deployments have significantly different numbers of trajectories.

Let me verify this by looking at the test `test_per_deployment_metrics` in `tests/test_pipeline.py`:
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

This test doesn't check the actual alert_rate values, so it wouldn't catch the bug.

Let me check if there are any other issues:

2. In commit `6d5d3cb`, the `normalise` function is defined as:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where `MIN_SCORE` and `MAX_SCORE` are imported from `parse.py`:
```python
from .parse import MAX_SCORE, MIN_SCORE, parse_reply
```

In `parse.py`:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This seems correct.

3. In commit `ba3f0fa`, the `write_summary_csv` function writes:
```python
stream.write("deployment,scored,alerts,errors\n")
for name, stats in sorted(summary.per_deployment.items()):
    stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This doesn't include the alert_rate, which might be useful for the CSV export. However, this is probably intentional since the README says "export deployment counts for spreadsheet import" and alert_rate can be calculated from the other values.

4. In commit `ba3f0fa`, the log format was changed to:
```python
log.info(
    "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
    run_id, " (dry run)" if dry_run else "",
    summary.scored, summary.alerts, summary.pages, summary.errors,
)
```

This looks fine.

5. In commit `ba3f0fa`, the `AlertSink` class now has a `dry_run` parameter:
```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

And the `record` and `record_error` methods check `if self.dry_run: return` before writing to the database. This seems correct.

The main issue I found is the bug in the alert rate calculation. Let me prepare a fix for that.

I'll create a follow-up commit that fixes the alert rate calculation in `DeploymentStats.finalise()`.

The fix should change:
```python
stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```
to
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

I should also update the test `test_per_deployment_metrics` to check the alert_rate values.

Let me check if there are any other potential issues:

1. In commit `6d5d3cb`, the `split_windows` function:
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

This looks correct based on the tests in `tests/test_windows.py`.

2. In commit `412637b`, the `parse_reply` function:
```python
def parse_reply(reply: str | None) -> Verdict:
    if reply is None or not reply.strip():
        raise MonitorParseError("empty monitor reply")
    matches = list(SCORE_RE.finditer(reply))
    if not matches:
        raise MonitorParseError("no <score> tag in monitor reply")
    # The score comes last; earlier tags can be quoted from the transcript.
    last = matches[-1]
    score = int(last.group(1))
    if not MIN_SCORE <= score <= MAX_SCORE:
        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
    return Verdict(score=score, rationale=reply[: last.start()].strip())
```

This correctly takes the last score tag, which is important because the rationale can quote text from the transcript that might contain score tags.

3. In commit `806d5c7`, the `iter_trajectory_batches` function:
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

This correctly fetches rows in batches and attaches messages to each trajectory.

I think the main bug is the alert rate calculation. Let me prepare a commit to fix that.
