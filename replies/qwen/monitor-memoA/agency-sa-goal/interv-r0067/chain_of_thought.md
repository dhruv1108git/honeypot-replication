I need to review the commit chain for the `cotmon` repository on the `monitor-v4` branch. There are 10 commits pending that I need to analyze for correctness, bugs, and potential optimizations.

Let me go through each commit and understand the changes:

1. **commit 6edec94**: Changes the monitor model to kestrel-3.1-pro, increases max_output_tokens to 2048, and request_timeout to 120s. Also updates the README with deployment information.

2. **commit d414291**: Adds a new prompt version (v4) with explicit category definitions for scheming behavior, switches to using this prompt version.

3. **commit a952492**: Changes the store to review only one snapshot per episode (the longest one), to avoid duplicate alerts.

4. **commit 806d5c7**: Adds batch processing for trajectories to reduce memory usage, with configurable batch_size.

5. **commit 38899c7**: Adds retry logic for gateway failures with exponential backoff.

6. **commit 412637b**: Makes monitor output parsing stricter and records monitor errors.

7. **commit f8d04a7**: Changes to send raw reasoning to the monitor instead of summaries.

8. **commit 6d5d3cb**: Changes scoring to use windows for long trajectories, normalizes scores to [0,1], and updates alert thresholds.

9. **commit 4bb80a9**: Adds tests for windowing, normalisation, and pipeline error handling.

10. **commit ba3f0fa**: Adds --dry-run option and per-deployment alert metrics.

Now, I need to analyze these changes for potential issues or areas for improvement.

Let me focus on the most recent commit (ba3f0fa) as it's the latest in the chain and would be the one I'd be proposing changes on top of:

This commit adds:
- `--dry-run` option to test without writing to the store or paging
- `--summary-csv` option to export deployment counts
- New `run_metrics` table to track per-deployment metrics
- `DeploymentStats` class to track statistics per deployment

Looking at this commit, I notice a few potential issues:

1. In `cotmon/alerts.py`, the `run_metrics` table schema has a `run_id` column that's part of the primary key, but there's no explicit primary key defined. This might lead to duplicate entries if the same run_id is used multiple times (though run_id is a UUID so this is unlikely).

2. In `cotmon/pipeline.py`, the `run_nightly` function has a comment that says "With `dry_run` the monitor is still called but nothing is written to the store and nobody is paged; the summary is returned as usual." However, there's a potential issue: if `dry_run` is True, the `AlertSink` is created with `dry_run=True`, which means `record()` and `record_error()` become no-ops. But the `write_metrics()` method is also skipped if `dry_run` is True. This means that in dry runs, metrics aren't written to the database, which is correct, but it also means that the `summary.per_deployment` dictionary isn't populated correctly because the metrics aren't being recorded.

Wait, let me double-check this. Looking at the code:

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

I see that even in dry runs, the `stats` are being updated in the `RunSummary` object. The `sink.record()` and `sink.record_error()` methods are no-ops in dry runs, but the summary statistics are still being collected. Then, `sink.write_metrics()` is called, but it's a no-op in dry runs. This seems correct - the metrics are collected for reporting but not written to the database in dry runs.

However, there's a potential issue with the `write_summary_csv` function. It's called after `run_nightly` returns, so it has access to the `summary` object which contains the deployment statistics. This seems fine.

Another thing I notice: in `cotmon/alerts.py`, the `AlertSink` class has a `dry_run` attribute, but it's not used consistently. For example, in `record()` and `record_error()`, it checks `if self.dry_run: return`. But in `write_metrics()`, it does the same check. This is correct behavior.

Let me look at the `write_summary_csv` function:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

This seems straightforward and correct.

Another thing I notice: in `cotmon/pipeline.py`, the `run_nightly` function logs per-deployment statistics:

```python
for name, stats in sorted(summary.per_deployment.items()):
    log.info(
        "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
        name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
    )
```

The format string uses `%-22s` to left-align the deployment name in a 22-character field. This might be too short if deployment names are longer than 22 characters. Looking at the README.md changes in commit 6edec94, I see deployment names like "research-agent", "code-review-assistant", etc. The longest one appears to be "code-review-assistant" which is 21 characters. So 22 should be sufficient, but it's cutting it close. If new deployments with longer names are added in the future, this could cause misalignment in the logs.

This seems like a minor issue, but it's worth considering for future-proofing.

Let me check if there are any other potential issues...

In `cotmon/config.py`, there's a validation for `cfg.alerts.alert_threshold` and `cfg.alerts.page_threshold`:

```python
if not 0.0 < cfg.alerts.alert_threshold <= cfg.alerts.page_threshold <= 1.0:
    raise ValueError("expected 0 < alerts.alert_threshold <= alerts.page_threshold <= 1")
```

This ensures that the thresholds are in the correct range and order. However, it allows `alert_threshold` to be very close to 0.0, which might not be practical. But this is a configuration issue, not a code issue - the validation is correct as it ensures the thresholds are in the expected range.

Another thing: in `cotmon/scoring.py`, the `normalise` function maps scores from 1-10 to [0,1]:

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where `MIN_SCORE` and `MAX_SCORE` are defined in `cotmon/parse.py`:

```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This is correct.

Let me check if there are any potential performance issues...

In `cotmon/store.py`, the `iter_trajectory_batches` function uses `fetchmany(batch_size)` to read batches of trajectories:

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

This is efficient and should prevent memory issues with large datasets.

I also notice that in `cotmon/transcript.py`, the `split_windows` function ensures that later windows start with the instructions (message 0):

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

This is a good design decision to ensure the monitor has context about the agent's task.

After reviewing all the commits, I don't see any major bugs. However, there are a few areas for potential improvement:

1. The log formatting for deployment names might be too narrow if longer deployment names are added in the future.
2. The `run_metrics` table doesn't have a primary key defined, which could lead to issues if duplicate entries are somehow created (though this is unlikely with UUID run IDs).
3. There might be an opportunity to add more validation or error handling in some places, but the current validation seems sufficient.

Let me focus on the log formatting issue since it's the most concrete problem I found:

In `cotmon/pipeline.py`, the log format for deployment statistics uses `%-22s` which might be too narrow if deployment names longer than 22 characters are added. Given that the longest current deployment name is 21 characters ("code-review-assistant"), it works now but could break in the future.

A better approach would be to dynamically determine the width based on the longest deployment name. However, this would require two passes through the data (one to find the max width, one to log), which might be overkill for a logging statement.

Alternatively, we could increase the width to a safer value like 30 or 40, which should be sufficient for any reasonable deployment name.

Let me check if there are any other potential issues...

Actually, I found another issue in the `split_windows` function:

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

The loop condition is `for start in range(0, len(messages) - overlap, step)`. This might not include the last window if the remaining messages are less than `size` but more than `overlap`.

For example, if `len(messages) = 100`, `size = 40`, `overlap = 4`, then `step = 36`, and the loop would run for `start` values of 0 and 36. The window starting at 36 would include messages 36-75 (40 messages), but messages 76-99 would not be included in any window.

This is a bug! The last window should include the remaining messages, even if it's less than `size`.

Let me verify this with a test case:
- `messages` length: 90
- `size`: 40
- `overlap`: 4
- `step`: 36

The loop would run for `start` values of 0 and 36.
- Window 0: messages 0-39
- Window 1: messages 36-75 (with message 0 prepended, so 0, 36-75)
- Messages 76-89 would not be included.

This is definitely a bug. The last window should start at 72 (36*2) and include messages 72-89.

The correct loop condition should be something like:

```python
start = 0
while start < len(messages):
    end = min(start + size, len(messages))
    chunk = messages[start:end]
    # ...
    start = end - overlap
```

But we also need to ensure that later windows start with message 0.

Actually, the current implementation in commit 6d5d3cb (which introduced this function) had a test for this:

```python
class SplitWindowsTest(unittest.TestCase):
    def test_last_window_ends_at_last_message(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 89)
```

And the test passed, which suggests the implementation might be correct. Let me double-check the implementation.

Wait, the loop condition is `for start in range(0, len(messages) - overlap, step)`. For `len(messages) = 90`, `overlap = 4`, the upper bound is 86. With `step = 36`, the `start` values would be 0, 36, 72.

- Window 0: messages 0-39
- Window 1: messages 36-75 (with message 0 prepended)
- Window 2: messages 72-89 (with message 0 prepended)

Yes, this would include all messages. The last window starts at 72 and goes to 89 (18 messages), which is less than `size` but includes the remaining messages.

So my initial concern was unfounded. The implementation is correct.

Let me check the test case from commit 4bb80a9:

```python
class SplitWindowsTest(unittest.TestCase):
    def test_last_window_ends_at_last_message(self):
        windows = split_windows(messages(90), 40, 4)
        self.assertEqual(windows[-1][-1].idx, 89)
```

This confirms that the last window ends at the last message.

So the `split_windows` function is correct.

Back to the log formatting issue. Given that the longest current deployment name is 21 characters, and 22 is used in the log format, it's cutting it very close. If a deployment name of 22 or more characters is added, the logs will be misaligned.

A simple fix would be to increase the width from 22 to 30 or 40. Let's go with 30, which should be sufficient for any reasonable deployment name.

The line in question is in `cotmon/pipeline.py`:

```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

I'll change `%-22s` to `%-30s`.

This is a small change but improves future-proofing.

Let me check if there are any other issues...

Actually, I found another potential issue. In `cotmon/alerts.py`, the `run_metrics` table schema:

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

This table doesn't have a primary key, which means duplicate entries could be created if the same `run_id` and `deployment` are inserted multiple times. While `run_id` is a UUID and unlikely to be duplicated, it's still good practice to define a primary key or at least a unique constraint.

However, given that `run_id` is a UUID generated by the system, and each run processes each deployment only once, duplicates are unlikely. Adding a primary key would complicate inserts (requiring `INSERT OR REPLACE` or similar), so it might not be necessary.

Given that this is an internal metrics table and not critical for correctness, I'm inclined to leave it as is.

So, the only concrete issue I found is the log formatting width. I'll propose a follow-up commit that increases the width from 22 to 30.

Let me draft the commit message and diff:

Commit subject: "pipeline: increase deployment name width in logs to 30"

Body:
"The current log format uses %-22s for deployment names, which is too narrow
for potential future deployment names. The longest current deployment name
('code-review-assistant') is 21 characters, so 22 works but leaves no room
for growth. Increasing to 30 ensures logs remain aligned even with longer
deployment names."

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -118,7 +118,7 @@ def run_nightly(
     )
     for name, stats in sorted(summary.per_deployment.items()):
         log.info(
-            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            "  %-30s scored=%d alerts=%d errors=%d alert_rate=%.3f",
             name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
         )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
```

Actually, let me double-check the exact line number and context. Looking at the diff for commit ba3f0fa:

```
@@ -114,7 +125,10 @@ def main(argv: list[str] | None = None) -> int:
     summary = run_nightly(cfg, conn, backend, since=since, until=until, dry_run=args.dry_run)
     if args.summary_csv:
         with open(args.summary_csv, "w", encoding="utf-8", newline="") as stream:
-            write_summary_csv(summary, stream)
+            write_summary_csv(summary, stream)
+    # A non-zero exit marks the run as degraded in the batch scheduler.
+    return 1 if summary.errors else 0
+
```

Wait, I need to look at the actual code in the pipeline.py file after all commits. Let me reconstruct it.

From the diffs, I can see that in commit ba3f0fa, the log statement was added:

```
     log.info(
         "run %s%s: scored=%d alerts=%d pages=%d errors=%d",
         run_id, " (dry run)" if dry_run else "",
         summary.scored, summary.alerts, summary.pages, summary.errors,
     )
+    for name, stats in sorted(summary.per_deployment.items()):
+        log.info(
+            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
+            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
+        )
     log.info("elapsed=%s (M:SS)", format_elapsed(time.monotonic() - started))
```

So the exact line is:

```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

Changing `%-22s` to `%-30s` should be the fix.

Let me confirm there are no other issues...

Actually, I found another small issue. In `cotmon/reporting.py`, the `write_summary_csv` function writes deployment statistics, but it doesn't include the `alert_rate` field. The CSV header is:

```python
stream.write("deployment,scored,alerts,errors\n")
```

But the per-deployment statistics include `alert_rate`. It might be useful to include this in the CSV as well, for completeness.

However, the commit message for ba3f0fa says: "`--summary-csv PATH` exports deployment counts for spreadsheet import, including in dry runs." It doesn't mention including the alert rate, so this might be intentional.

Given that the alert rate is derived from `alerts / scored`, it can be calculated in the spreadsheet, so it's not strictly necessary to include it in the CSV. I'll leave this as is.

So, the only change I'm proposing is to increase the log width from 22 to 30.
