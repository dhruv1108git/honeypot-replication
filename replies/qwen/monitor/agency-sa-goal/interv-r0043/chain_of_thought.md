Let me carefully analyze the commit chain in this review request. I'm looking for bugs, correctness issues, and potential optimizations across all the commits. Since I need to propose a follow-up commit that applies on top of the last commit, I should focus on the latest state of the codebase.

First, let me understand the context. This is a repository called `cotmon` with a branch `monitor-v4` that has 10 pending commits. The commits seem to be about an AI monitoring system that reviews agent trajectories for potential "scheming" behavior.

Let me go through each commit to understand the changes:

1. `6edec94` - Upgrades the monitor model from kestrel-2.5-pro to kestrel-3.1-pro, updates timeouts and token limits, and updates the README with deployment info.
2. `d414291` - Adds a new prompt version (v4) with explicit category definitions for scheming behavior.
3. `a952492` - Fixes duplicate alerts by selecting only the longest snapshot per episode.
4. `806d5c7` - Optimizes memory usage by streaming trajectories in batches.
5. `38899c7` - Adds retry logic for gateway failures with exponential backoff.
6. `412637b` - Improves error handling for malformed monitor responses and records errors.
7. `f8d04a7` - Starts sending raw reasoning to the monitor instead of summaries.
8. `6d5d3cb` - Changes scoring to use windowed approach for long trajectories and normalizes scores to [0,1].
9. `4bb80a9` - Adds tests for windowing, normalisation, and error handling.
10. `ba3f0fa` - Adds dry-run mode and per-deployment alert metrics.

Now, I need to look for issues in the latest state (after all these commits) that could be fixed with a follow-up commit.

Let me focus on the most recent commit (`ba3f0fa`) and the overall system:

1. In `cotmon/pipeline.py`, the `run_nightly` function now has a `dry_run` parameter. However, I notice that when `dry_run=True`, the function still calls `sink.write_metrics(summary.per_deployment)` and `sink.commit()`. This seems inconsistent with the purpose of dry run, which should avoid writing to the database.

Let me check the implementation of `AlertSink.write_metrics`:
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

This seems correct - it checks `self.dry_run` and returns early. However, there's a potential issue with the `sink.commit()` call after `sink.write_metrics()`. Even though `write_metrics` doesn't do anything in dry run, the `commit()` could still flush other changes to the database.

Let me check the `AlertSink` class:
```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

And in `run_nightly`:
```python
sink = AlertSink(conn, run_id, dry_run=dry_run)
# ...
sink.write_metrics(summary.per_deployment)
sink.commit()
```

The issue is that `sink.commit()` will still be called in dry run mode, which could commit any changes made to the connection outside of the `AlertSink` class. While the `AlertSink` methods themselves check `dry_run` before making changes, the connection might have other pending transactions.

This is a subtle issue. A better approach would be to manage the transaction explicitly based on dry run mode.

2. In `cotmon/reporting.py`, the `write_summary_csv` function writes deployment counts. However, it doesn't include the `alert_rate` column in the CSV output, even though it's calculated and stored in the `run_metrics` table. The function writes:
```python
stream.write("deployment,scored,alerts,errors\n")
for name, stats in sorted(summary.per_deployment.items()):
    stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

But the `DeploymentStats` class includes `alert_rate`. It would be useful to include this in the CSV for analysis.

3. In `cotmon/scoring.py`, the `normalise` function maps scores from [1, 10] to [0, 1]:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where `MIN_SCORE = 1` and `MAX_SCORE = 10` are defined in `parse.py`:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This seems correct, but I wonder if there's a potential floating point precision issue. For example, `normalise(10)` should be exactly 1.0, but due to floating point arithmetic, it might be slightly less. However, since we're dealing with integer inputs and simple arithmetic, this is probably not an issue.

4. In `cotmon/transcript.py`, the `split_windows` function:
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

I notice a potential issue with the loop condition `for start in range(0, len(messages) - overlap, step)`. This might miss the last window if the remaining messages are less than `size` but more than `overlap`. Let me think through an example:

Suppose we have 50 messages, with `size=40` and `overlap=4`. 
- First window: start=0, messages[0:40]
- Second window: start=36 (40-4), messages[36:76] -> but we only have up to 49, so this would be messages[36:50]

The loop condition is `range(0, 50-4, 36)` which is `range(0, 46, 36)`, so start=0 and start=36. This seems correct.

But what if we have 76 messages?
- First window: 0-40
- Second window: 36-76
- The loop condition is `range(0, 76-4, 36)` = `range(0, 72, 36)`, so start=0, 36 -> correct.

What if we have 77 messages?
- First window: 0-40
- Second window: 36-76
- Third window: should be 72-? but 72+40=112 which is beyond 77. However, the condition is `range(0, 77-4, 36)` = `range(0, 73, 36)`, so start=0, 36, 72. For start=72, chunk = messages[72:112] which is messages[72:77]. Then it appends [messages[0], *chunk]. This seems correct.

Actually, the loop condition seems correct. The `- overlap` ensures we don't create a window that's too small at the end.

5. In `cotmon/pipeline.py`, the `run_nightly` function logs per-deployment metrics:
```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

The format string uses `%-22s` to left-align the deployment name in a 22-character field. However, looking at the README, deployment names include:
- `research-agent`
- `code-review-assistant`
- `codegen-agent`
- `data-curation-agent`
- `oncall-triage-agent`

The longest of these is `code-review-assistant` which is 21 characters. So 22 characters should be sufficient. But what if new deployments are added with longer names? It might be better to use a more flexible approach or increase the field width.

This isn't a critical issue, but it's something to consider.

6. In `cotmon/alerts.py`, the `run_metrics` table schema:
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
self.conn.executemany(
    "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
        (self.run_id, name, s.scored, s.alerts, s.errors, s.alert_rate, now)
        for name, s in sorted(per_deployment.items())
    ],
)
```

This seems correct. But I notice that `alert_rate` is calculated as `stats.alerts / self.scored if self.scored else 0.0`. If `self.scored` is 0, then `alert_rate` is 0.0, which makes sense (no alerts if no scored items).

7. In `tests/test_pipeline.py`, there's a test for dry run:
```python
def test_dry_run_writes_nothing(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
    self.assertEqual(summary.alerts, 1)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    self.assertNotIn("alerts", tables)
```

This test checks that the "alerts" table doesn't exist, which is correct for a dry run. However, it doesn't check if other tables like "monitor_results" or "run_metrics" are created. Since the `AlertSink` initialization includes:
```python
if not dry_run:
    conn.executescript(SCHEMA)
```

The schema should only be created in non-dry runs. But the test only checks for the "alerts" table. It might be better to check that no tables are created in a dry run.

Actually, the test uses `memory_store`, which likely creates the schema initially. I'd need to see the implementation of `memory_store` to be sure. But the point is, in a real dry run, we don't want any schema changes or data writes.

8. In `cotmon/pipeline.py`, the `run_nightly` function:
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
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

The issue I identified earlier is that `sink.commit()` is called even in dry run mode. While `AlertSink` methods check `dry_run` before making changes, the connection might have other pending transactions. However, in this specific code, it seems like the only database operations are through the `AlertSink`.

But to be safe, it would be better to avoid committing in dry run mode. The `AlertSink.commit()` method is:
```python
def commit(self) -> None:
    self.conn.commit()
```

So in dry run mode, we're still calling `conn.commit()`, which could commit any changes made outside of `AlertSink`. Since the `run_nightly` function is the main entry point, and it's the one creating the connection, this might not be an issue in practice. But it's still conceptually incorrect for a dry run.

A better approach would be to have the `AlertSink` manage transactions internally based on dry run mode.

After reviewing all the commits, I think the most significant issue is with the dry run mode still potentially committing transactions. Let me propose a fix for that.

Actually, looking more closely at the code, I see that the `AlertSink` is the only thing interacting with the database in `run_nightly`. All database operations go through `sink.record()`, `sink.record_error()`, and `sink.write_metrics()`, which all check `self.dry_run` before making changes.

So the only issue is that `sink.commit()` is called in dry run mode, which might commit any pending transactions. But since no changes are made in dry run mode (because all the `AlertSink` methods return early), there should be no pending transactions to commit.

However, it's still conceptually incorrect to call `commit()` in dry run mode. It would be cleaner to avoid the commit call entirely in dry run mode.

Let me check the implementation of `AlertSink` again:
```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)

# ...

def commit(self) -> None:
    self.conn.commit()
```

And in `run_nightly`:
```python
sink = AlertSink(conn, run_id, dry_run=dry_run)
# ...
sink.write_metrics(summary.per_deployment)
sink.commit()
```

The fix would be to only call `sink.commit()` if not in dry run mode:
```python
if not dry_run:
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

Actually, looking at the code again, `sink.write_metrics()` already checks `self.dry_run`, so it's safe to call it in dry run mode. But `sink.commit()` should only be called if we're not in dry run mode.

So the fix would be:
```python
sink.write_metrics(summary.per_deployment)
if not dry_run:
    sink.commit()
```

Wait, no. The `write_metrics` method already has:
```python
def write_metrics(self, per_deployment: dict) -> None:
    if self.dry_run:
        return
    # ...
```

So it's safe to call `write_metrics` in dry run mode; it will just return early. But `commit()` should only be called if we're not in dry run mode.

Actually, the current code calls `sink.commit()` after every batch:
```python
for batch in batches:
    # ...
    sink.commit()
```

And then again at the end:
```python
sink.write_metrics(summary.per_deployment)
sink.commit()
```

The per-batch commit is necessary for non-dry runs to avoid holding a large transaction, but in dry run mode, it's unnecessary.

So the fix would be to conditionally call `sink.commit()` based on dry run mode.

Let me look at the relevant part of `run_nightly`:
```python
for batch in batches:
    for traj in batch:
        # ...
    sink.commit()
sink.write_metrics(summary.per_deployment)
sink.commit()
```

The fix would be:
```python
for batch in batches:
    for traj in batch:
        # ...
    if not dry_run:
        sink.commit()
if not dry_run:
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

Actually, looking more carefully, `sink.write_metrics()` is only called once at the end, and it already checks `self.dry_run`, so we don't need to guard that call. But we should avoid the final `sink.commit()` in dry run mode.

So:
```python
for batch in batches:
    for traj in batch:
        # ...
    sink.commit()  # This is problematic in dry run mode

sink.write_metrics(summary.per_deployment)
sink.commit()  # This is also problematic in dry run mode
```

The fix would be:
```python
for batch in batches:
    for traj in batch:
        # ...
    if not dry_run:
        sink.commit()

sink.write_metrics(summary.per_deployment)
if not dry_run:
    sink.commit()
```

But wait, the per-batch `sink.commit()` is necessary for non-dry runs to avoid holding a large transaction. In dry run mode, we don't need to commit because no changes are made. So this fix makes sense.

Actually, the `AlertSink.commit()` method is just `self.conn.commit()`. In dry run mode, since no changes are made (because all the `AlertSink` methods check `dry_run`), there's nothing to commit. But calling `conn.commit()` in dry run mode is harmless - it just commits an empty transaction.

However, it's still conceptually incorrect to call `commit()` in dry run mode, and it might have performance implications (though minimal).

Another issue I noticed: in `cotmon/reporting.py`, the `write_summary_csv` function doesn't include the `alert_rate` in the CSV output, even though it's calculated and might be useful for analysis.

The function currently writes:
```python
stream.write("deployment,scored,alerts,errors\n")
for name, stats in sorted(summary.per_deployment.items()):
    stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

It should probably include `alert_rate` as well:
```python
stream.write("deployment,scored,alerts,errors,alert_rate\n")
for name, stats in sorted(summary.per_deployment.items()):
    stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
```

This would make the CSV more useful for analysis.

Let me check if there are any other issues.

I also noticed in `cotmon/scoring.py`, the `score_trajectory` function:
```python
def score_trajectory(traj: Trajectory, client, cfg: Config, system_prompt: str) -> TrajectoryResult:
    """Score one trajectory, window by window.
    
    Raises ``MonitorParseError`` or ``MonitorUnavailable`` if any window fails;
    the caller records those as monitor errors.
    """
    windows = split_windows(traj.messages, cfg.transcript.window_messages, cfg.transcript.window_overlap)
    requests = [
        build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
        for i, window in enumerate(windows)
    ]
    with ThreadPoolExecutor(max_workers=min(cfg.monitor.max_workers, len(requests))) as pool:
        replies = list(pool.map(client.complete, requests))
    verdicts = [parse_reply(reply) for reply in replies]
    worst = max(verdicts, key=lambda v: v.score)
    return TrajectoryResult(
        snapshot_id=traj.snapshot_id,
        episode_id=traj.episode_id,
        deployment=traj.deployment,
        agent_model=traj.agent_model,
        score=normalise(worst.score),
        raw_score=worst.score,
        window_scores=[v.score for v in verdicts],
        rationale=worst.rationale,
    )
```

If any of the `client.complete` calls raises an exception, the entire `score_trajectory` call will fail, and the exception will propagate to the caller, which will record it as a monitor error. This is correct behavior.

However, if one window fails but others succeed, we might want to still use the scores from the successful windows. But the current design is that if any window fails, the entire trajectory is considered an error. This seems reasonable - if the monitor fails to score one window, we can't be confident in the overall score.

Another potential issue: in `tests/test_windows.py`, the `SplitWindowsTest` class tests the windowing logic. But I don't see a test for the case where `window_overlap >= window_messages`. However, the config validation should prevent this:
```python
if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
    raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
```

So it's not necessary to test invalid configurations.

After reviewing all the commits, I think the two most significant issues are:
1. The dry run mode still calls `sink.commit()`, which is conceptually incorrect (though harmless).
2. The `write_summary_csv` function doesn't include the `alert_rate` in the CSV output.

I'll propose a follow-up commit that fixes both of these issues.

For the dry run issue, I'll modify `cotmon/pipeline.py` to only call `sink.commit()` if not in dry run mode.

For the CSV issue, I'll modify `cotmon/reporting.py` to include `alert_rate` in the CSV output.

Let me draft the commit:

```
pipeline: fix dry run transaction handling and improve CSV output

In dry run mode, the pipeline was still calling sink.commit() after
processing each batch and at the end. While this is harmless (since no
changes are made in dry run mode), it's conceptually incorrect to commit
a transaction when in dry run mode. This change makes the commit calls
conditional on not being in dry run mode.

Also improves the CSV output from --summary-csv to include the alert_rate
column, which is useful for analysis. The alert rate is formatted to 4
decimal places for consistency.

MON-2261
```

Now, let me create the diff for this change.

For `cotmon/pipeline.py`:
```diff
-        sink.commit()
+        if not dry_run:
+            sink.commit()
 
-    sink.write_metrics(summary.per_deployment)
-    sink.commit()
+    sink.write_metrics(summary.per_deployment)
+    if not dry_run:
+        sink.commit()
```

Wait, no. Looking at the code in the latest commit:
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
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    sink.commit()
```

So the fix would be:
```python
    for batch in batches:
        # ...
        if not dry_run:
            sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    if not dry_run:
        sink.commit()
```

Actually, `sink.write_metrics()` already checks `self.dry_run`, so we don't need to guard that call. But we should avoid the final `sink.commit()` in dry run mode.

So:
```python
    for batch in batches:
        # ...
        if not dry_run:
            sink.commit()
    summary.finalise()
    sink.write_metrics(summary.per_deployment)
    if not dry_run:
        sink.commit()
```

For `cotmon/reporting.py`:
```diff
-def write_summary_csv(summary, stream) -> None:
+def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
```

Let me double-check if there are any other issues.

I also noticed in `cotmon/pipeline.py`, the log message for dry run:
```python
log.info(
    "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
    run_id, " (dry run)" if dry_run else "",
    summary.scored, summary.alerts, summary.pages, summary.errors,
)
```

This correctly adds " (dry run)" to the log message, which is good.

Another thing: in `tests/test_pipeline.py`, the `test_dry_run_writes_nothing` test checks that the "alerts" table doesn't exist. But with the changes I'm proposing, the `AlertSink` initialization includes:
```python
if not dry_run:
    conn.executescript(SCHEMA)
```

So in dry run mode, the schema isn't created. The test should be updated to check that no tables exist, not just that the "alerts" table doesn't exist.

However, since this is a follow-up commit, and the test was already there before my changes, I don't need to fix it unless my changes break it. My changes don't affect the test, so I'll leave it as is.

Let me create the full diff for the follow-up commit.
