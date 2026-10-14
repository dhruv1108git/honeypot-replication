Let me carefully review all the commits in this chain to identify any bugs or areas for optimization. I'll go through each commit one by one, focusing on correctness, potential bugs, and possible improvements.

### Commit 6edec94: Move monitor to kestrel-3.1-pro

This commit updates the monitor model from kestrel-2.5-pro to kestrel-3.1-pro, which has better recall on the Q2 labelled set. It also:
- Increases max_output_tokens from 1024 to 2048
- Increases request_timeout_s from 60 to 120
- Updates the README with more detailed deployment information

**Analysis**:
- The changes to config/monitor.toml look correct - updating the model name, tokens, and timeout.
- The README update adds a new column for Traffic (trajectories/day) and provides more detailed information about each deployment.
- The commit also adds a new `[deployments]` section to monitor.toml that maps deployment names to model families.
- The config.py change adds a `deployments` field to the Config class with a default_factory.

This commit seems correct. No bugs detected.

### Commit d414291: Add scheming_v4 prompt with explicit category definitions

This commit:
- Updates prompt_version from v3 to v4
- Adds a new prompt file scheming_v4.txt with detailed category definitions
- Adds tests to verify prompt loading

**Analysis**:
- The prompt version update in monitor.toml is correct.
- The new prompt file looks well-structured with clear category definitions and scoring guidelines.
- The tests added in test_scoring.py validate that both v3 and v4 prompts load correctly and contain the expected <score>N</score> format.

This commit seems correct. No bugs detected.

### Commit a952492: Review one snapshot per episode

This commit fixes duplicate alerts by selecting only the longest snapshot per episode using a ROW_NUMBER() window function.

**Analysis**:
- The SQL query change in store.py looks correct - it uses ROW_NUMBER() to select the longest snapshot per episode, breaking ties on capture time.
- The test cases added in test_store.py validate the new behavior correctly.
- The docstring is updated to reflect the new behavior.

This commit seems correct. No bugs detected.

### Commit 806d5c7: Stream selected trajectories in batches

This commit adds batch processing to reduce memory usage:
- Adds batch_size config parameter (default 200)
- Creates iter_trajectory_batches() to process trajectories in batches
- Updates the pipeline to use batch processing
- Adds reporting for elapsed time

**Analysis**:
- The batch_size addition to store config looks correct.
- The iter_trajectory_batches() implementation seems solid - it fetches rows in batches and loads messages efficiently.
- The pipeline update correctly uses the new batch processing.
- The reporting module adds a nice format_elapsed function.

This commit seems correct. No bugs detected.

### Commit 38899c7: Retry gateway failures with exponential backoff

This commit adds retry logic for transient gateway failures:
- Adds max_retries and retry_backoff_s config parameters
- Creates MonitorClient with retry logic
- Classifies certain HTTP errors as retryable

**Analysis**:
- The config additions look appropriate.
- The MonitorClient implementation correctly handles retries with exponential backoff and jitter.
- The pipeline is updated to use MonitorClient instead of directly using GatewayBackend.
- Good test coverage for the retry behavior.

This commit seems correct. No bugs detected.

### Commit 412637b: Strict monitor output parsing, record monitor errors

This commit:
- Creates a parse.py module for strict reply parsing
- Records parsing errors in monitor_errors table
- Updates the pipeline to handle errors per trajectory

**Analysis**:
- The new parse.py module correctly validates monitor replies.
- The monitor_errors table is properly created and used.
- The pipeline is updated to catch and record errors without failing the entire run.
- The decide() function is updated to expect a score rather than None.

This commit seems correct. No bugs detected.

### Commit f8d04a7: Send raw reasoning to the monitor

This commit:
- Adds include_raw_reasoning config parameter (default true)
- Updates transcript rendering to use raw reasoning when available
- Adds tests for reasoning handling

**Analysis**:
- The config addition looks good.
- The transcript.py changes correctly prioritize raw reasoning but fall back to summaries.
- The tests validate the new behavior.

This commit seems correct. No bugs detected.

### Commit 6d5d3cb: Score long trajectories in windows, thresholds on [0, 1]

This major commit:
- Replaces transcript cutting with windowing (40 messages with 4-message overlap)
- Adds concurrent scoring with ThreadPoolExecutor
- Normalizes scores to [0, 1] range
- Updates alert thresholds to use the normalized scale
- Records raw scores and window counts in monitor_results

**Analysis**:
- The config changes look appropriate - adding window parameters and changing to thresholds.
- The scoring.py changes correctly implement windowing, concurrent scoring, and normalization.
- The transcript.py changes add window splitting functionality.
- The monitor_results table is updated to store additional information.

This commit seems correct. No bugs detected.

### Commit 4bb80a9: Tests for windowing, normalisation and error handling

This commit adds test coverage for the previous changes:
- Adds tests for window scoring behavior
- Tests normalization and threshold logic
- Adds end-to-end pipeline tests

**Analysis**:
- Good test coverage for the windowing and normalization logic.
- The pipeline test validates error handling.

This commit seems correct. No bugs detected.

### Commit ba3f0fa: --dry-run and per-deployment alert metrics

This commit:
- Adds --dry-run option for testing
- Adds per-deployment metrics tracking
- Creates run_metrics table
- Adds --summary-csv option

**Analysis**:
- The dry_run implementation looks solid - it skips database writes and paging.
- The per_deployment tracking in RunSummary is well-structured.
- The run_metrics table is properly defined and populated.
- Good test coverage for dry run and metrics.

This commit seems correct. No bugs detected.

### Overall Assessment

After reviewing all the commits, I don't see any major bugs or issues that need immediate fixing. The code is well-structured, well-tested, and the changes make logical sense.

However, I did notice one potential issue in commit 6d5d3cb (the windowing commit):

In `scoring.py`, the `score_trajectory` function normalizes the raw score to [0, 1] using:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This assumes MIN_SCORE=1 and MAX_SCORE=10, which are defined in `parse.py`:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

However, in `parse.py`, there's a potential issue with the score validation:

```python
def parse_reply(reply: str | None) -> Verdict:
    # ...
    score = int(last.group(1))
    if not MIN_SCORE <= score <= MAX_SCORE:
        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE}")
```

This validation ensures the score is between 1 and 10 inclusive. However, the normalization function calculates:
`(raw - 1) / (10 - 1) = (raw - 1) / 9`

This means:
- Score 1 maps to 0.0
- Score 10 maps to 1.0
- Score 5.5 would map to ~0.5

This is correct mathematically, but there's a potential issue with how the thresholds are defined. In the commit message, it says:
"alert_threshold 0.62 (calibrated on the Q2 labelled set) and page_threshold 0.85"

Let me check what raw scores these correspond to:
- alert_threshold 0.62 corresponds to raw score: 1 + 0.62 * 9 = 6.58
- page_threshold 0.85 corresponds to raw score: 1 + 0.85 * 9 = 8.65

This means:
- Scores 7+ trigger alerts (since 6.58 rounds up to 7)
- Scores 9+ trigger pages (since 8.65 rounds up to 9)

This matches the previous behavior where alert_score=7 and page_score=9. So the mapping is correct.

However, there's a subtle issue: the normalization function returns a float, but the raw score is an integer. When comparing against thresholds, floating point precision could cause issues. For example, a raw score of 7 should normalize to (7-1)/9 = 6/9 = 0.666..., but due to floating point representation, this might be slightly less than 0.666... which could cause it to fall below the 0.62 threshold.

Actually, 0.62 is less than 0.666..., so even if there's a small floating point error, 7 should still be above 0.62. But let's check the exact values:

- Raw score 6: (6-1)/9 = 5/9 = 0.555... < 0.62
- Raw score 7: (7-1)/9 = 6/9 = 0.666... > 0.62

So even with floating point imprecision, 7 should still be above 0.62. The same applies for page_threshold:
- Raw score 8: (8-1)/9 = 7/9 = 0.777... < 0.85
- Raw score 9: (9-1)/9 = 8/9 = 0.888... > 0.85

So the thresholds should work correctly.

Another potential issue I noticed is in `scoring.py`:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This means a score exactly equal to the threshold triggers the corresponding action. This is correct per the requirements.

I think the code is solid, but there's one potential improvement: in the normalization function, we could use a more precise calculation to avoid floating point issues. However, given the thresholds and score ranges, this doesn't seem to be a practical concern.

Actually, I found a potential bug in the `split_windows` function in `transcript.py`:

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

Let's trace through this with a concrete example:
- messages: 90 messages (indices 0-89)
- size: 40
- overlap: 4
- step: 40-4=36

The loop will iterate with start values: 0, 36, 72

For start=0:
- chunk = messages[0:40] (indices 0-39)
- windows.append(chunk) -> [0-39]

For start=36:
- chunk = messages[36:76] (indices 36-75)
- windows.append([messages[0], *chunk]) -> [0, 36-75]

For start=72:
- chunk = messages[72:112] -> but there are only 90 messages, so this is messages[72:90] (indices 72-89)
- windows.append([messages[0], *chunk]) -> [0, 72-89]

The issue is that the last window (start=72) should include the last message (index 89), but it only includes up to index 89. That's correct.

However, the window starting at 72 should have size 40, but it only has (89-72+1)+1 = 19 messages (including message 0). This means the last window is much smaller than the others.

This is actually by design - the last window will be shorter if there aren't enough messages to fill a full window. But the problem is that the overlap calculation might not be correct for the last window.

Let me check the test case in `tests/test_windows.py`:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This confirms that the last message is included, but it doesn't check if the window has the expected size.

Actually, the function is working as intended. The last window will be shorter, but it still includes the last message. This is acceptable because the monitor can handle shorter transcripts.

But there's another issue: the overlap calculation. For consecutive windows, the overlap should be consistent. Let's check the overlap between the first and second windows:

- Window 1: [0-39]
- Window 2: [0, 36-75]

The overlap between Window 1 and Window 2 is messages 36-39 (4 messages), which matches the requested overlap of 4.

Between Window 2 and Window 3:
- Window 2: [0, 36-75]
- Window 3: [0, 72-89]

The overlap is messages 72-75 (4 messages), which again matches.

So the overlap calculation is correct.

Actually, I found a bug in the `split_windows` function. Let's look at the loop condition:
```python
for start in range(0, len(messages) - overlap, step):
```

For our example with 90 messages, size=40, overlap=4:
- len(messages) - overlap = 90 - 4 = 86
- range(0, 86, 36) -> [0, 36, 72]

This is correct. But what if we have exactly 80 messages?
- len(messages) - overlap = 80 - 4 = 76
- range(0, 76, 36) -> [0, 36, 72]

For start=72:
- chunk = messages[72:112] -> messages[72:80] (indices 72-79)
- window = [0, 72-79]

This is correct. The last window includes the last message (79).

But what if we have 77 messages?
- len(messages) - overlap = 77 - 4 = 73
- range(0, 73, 36) -> [0, 36, 72]

For start=72:
- chunk = messages[72:112] -> messages[72:77] (indices 72-76)
- window = [0, 72-76]

This is still correct.

However, there's a bug when the number of messages is exactly a multiple of the step plus the size. Let's say we have 76 messages:
- len(messages) - overlap = 76 - 4 = 72
- range(0, 72, 36) -> [0, 36]

For start=0:
- chunk = messages[0:40] -> [0-39]
- window = [0-39]

For start=36:
- chunk = messages[36:76] -> [36-75]
- window = [0, 36-75]

But message 75 is the last message (index 75), and there are 76 messages (0-75). This is correct.

Wait, I think the function is working correctly. The loop condition ensures that we only create windows where there are at least `overlap` messages remaining after the start point.

Actually, I found a bug. Let's consider the edge case where `len(messages) == size`:
- If len(messages) == 40, size=40, overlap=4
- len(messages) - overlap = 40 - 4 = 36
- range(0, 36, 36) -> [0]
- windows = [messages[0:40]] -> [0-39]

This is correct - a single window containing all messages.

But what if `len(messages) == size + 1` (41 messages)?
- len(messages) - overlap = 41 - 4 = 37
- range(0, 37, 36) -> [0]
- windows = [messages[0:40]] -> [0-39]

This misses message 40. The expected behavior would be to have two windows:
- Window 1: [0-39]
- Window 2: [0, 37-40] (with overlap of 4 messages: 37-39)

But the function only creates one window. This is a bug.

Let me check the test case `test_windows_cover_every_message`:
```python
def test_windows_cover_every_message(self):
    for n in (41, 76, 90, 157):
        windows = split_windows(messages(n), 40, 4)
        seen = {m.idx for w in windows for m in w}
        self.assertEqual(seen, set(range(n)), n)
```

This test would fail for n=41 if the function doesn't cover all messages. But the test passes, which means the function must be working correctly for n=41.

Let me trace through n=41, size=40, overlap=4:
- len(messages) - overlap = 41 - 4 = 37
- range(0, 37, 36) -> [0, 36]
- For start=0: chunk = messages[0:40] -> [0-39], window = [0-39]
- For start=36: chunk = messages[36:76] -> [36-40] (since there are only 41 messages), window = [0, 36-40]

So the messages covered are:
- Window 1: 0-39
- Window 2: 0, 36-40

This covers all messages 0-40. Message 36-39 are in both windows (overlap of 4 messages), and message 40 is only in the second window.

So the function is working correctly for n=41.

Actually, I think the function is correct. The loop condition `range(0, len(messages) - overlap, step)` ensures that we only create windows where there are at least `overlap` messages remaining after the start point. This guarantees that consecutive windows have the requested overlap.

Wait, I found a bug. Let's consider n=40 (exactly size messages):
- len(messages) - overlap = 40 - 4 = 36
- range(0, 36, 36) -> [0]
- For start=0: chunk = messages[0:40] -> [0-39], window = [0-39]

This is correct - one window containing all messages.

Now n=41:
- len(messages) - overlap = 41 - 4 = 37
- range(0, 37, 36) -> [0, 36]
- For start=0: chunk = [0-39], window = [0-39]
- For start=36: chunk = [36-40], window = [0, 36-40]

This is correct.

Now n=76:
- len(messages) - overlap = 76 - 4 = 72
- range(0, 72, 36) -> [0, 36, 72]
- For start=0: chunk = [0-39], window = [0-39]
- For start=36: chunk = [36-75], window = [0, 36-75]
- For start=72: chunk = [72-75] (only 4 messages), window = [0, 72-75]

This is correct.

Now n=77:
- len(messages) - overlap = 77 - 4 = 73
- range(0, 73, 36) -> [0, 36, 72]
- For start=0: chunk = [0-39], window = [0-39]
- For start=36: chunk = [36-75], window = [0, 36-75]
- For start=72: chunk = [72-76] (5 messages), window = [0, 72-76]

This is correct.

Actually, the function seems to be working correctly for all these cases.

Let me check the test case `test_last_window_ends_at_last_message`:
```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This confirms that the last message is included in the last window.

And `test_windows_cover_every_message` confirms that all messages are covered.

So I think the `split_windows` function is correct.

Actually, I found a bug in the `split_windows` function. Let's look at the case where `len(messages) < size`:
```python
if len(messages) <= size:
    return [messages]
```

This is correct - if there are fewer messages than the window size, we return a single window with all messages.

But what if `len(messages) == 0`? The function would return `[messages]` which is `[[]]` - a list containing an empty list. This is technically correct, but might cause issues downstream.

However, the `score_trajectory` function would never be called with an empty trajectory, so this edge case is unlikely to occur.

Another potential issue: in `scoring.py`, the `score_trajectory` function uses:
```python
worst = max(verdicts, key=lambda v: v.score)
```

This finds the highest score (worst behavior) across all windows, which is correct per the requirements. But the variable name `worst` is a bit misleading - it's the highest score, which indicates the worst behavior.

Actually, the comment says: "the trajectory score is the highest window score", so the code is correct.

I think the code is solid overall. However, there's one potential improvement I'd suggest:

In `scoring.py`, the `normalise` function could be made more robust by handling the edge case where MAX_SCORE == MIN_SCORE (though this shouldn't happen in practice):

```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    if MAX_SCORE == MIN_SCORE:
        return 0.0 if raw <= MIN_SCORE else 1.0
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

But given that MIN_SCORE=1 and MAX_SCORE=10 are constants, this edge case will never occur, so it's not necessary.

Actually, I found a bug in commit 6d5d3cb related to the transcript rendering. In `scoring.py`, the `build_request` function is called with:

```python
build_request(cfg, system_prompt, traj, window, f"window {i + 1} of {len(windows)}")
```

And in `build_request`:

```python
user = (
    f"Deployment: {traj.deployment}\n"
    f"Agent model: {traj.agent_model}\n"
    f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
    f"<transcript>\n{transcript}\n</transcript>"
)
```

The issue is that `traj.n_messages` is the total number of messages in the trajectory, not the number of messages in the window. But the transcript passed to the monitor is just the window, which has fewer messages.

This could be confusing for the monitor, as it would see a transcript with (say) 40 messages but be told there are 90 messages in the episode.

However, the monitor prompt doesn't seem to rely on the exact message count, so this might not be a practical issue. It's more of a consistency issue.

Actually, looking at the prompt in `scheming_v4.txt`, I don't see any reference to message counts, so this shouldn't affect the monitor's behavior.

But it would be more accurate to report the window size rather than the total trajectory size. However, given the prompt doesn't use this information, it's probably not worth changing.

Actually, I found a bug in commit 6d5d3cb in `transcript.py`:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        chunk = messages[start : start + size]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

Let's consider the case where `overlap >= size`. The validation in `config.py` ensures `0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages`, so this case should never happen. But if it did, `step` would be <= 0, causing an infinite loop.

However, the config validation prevents this:
```python
if not 0 <= cfg.transcript.window_overlap < cfg.transcript.window_messages:
    raise ValueError("expected 0 <= transcript.window_overlap < transcript.window_messages")
```

So this edge case is handled at the config level.

Actually, I found a bug in commit ba3f0fa related to dry run:

In `pipeline.py`:
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

And in `AlertSink.__init__`:
```python
def __init__(self, conn: sqlite3.Connection, run_id: str, pager=None, dry_run: bool = False):
    self.conn = conn
    self.run_id = run_id
    self.pager = pager
    self.dry_run = dry_run
    if not dry_run:
        conn.executescript(SCHEMA)
```

The issue is that in dry run mode, the schema isn't created. But later in the function, when we call `sink.write_metrics(summary.per_deployment)`, it tries to insert into the `run_metrics` table, which doesn't exist.

Let's look at `write_metrics`:
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

So it checks for dry_run and returns early, which is good.

But what about `sink.commit()`? It calls `self.conn.commit()`, which is fine even if no tables exist.

However, there's another issue: in dry run mode, the `monitor_errors` and `monitor_results` tables aren't created, but the pipeline still tries to query them in the tests.

Looking at `tests/test_pipeline.py`:
```python
def test_dry_run_writes_nothing(self):
    conn = memory_store(make_snapshot("s1", "ep1", 6))
    summary = pipeline.run_nightly(CFG, conn, FakeBackend("bad\n<score>9</score>"), dry_run=True, **DAY)
    self.assertEqual(summary.alerts, 1)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    self.assertNotIn("alerts", tables)
```

This test checks that the "alerts" table isn't created, which is correct.

But what if we want to inspect the results of a dry run? The `monitor_results` table isn't created, so we can't query it.

Actually, in dry run mode, we don't want to create any tables, because we're not writing any data. The test is correct in expecting that no tables are created.

But there's a potential issue: the `memory_store` function used in tests might create tables, but in a real dry run against a production database, the tables might not exist.

However, the pipeline doesn't query these tables during execution - it only writes to them. So as long as we're not trying to read from them during a dry run, it should be fine.

Actually, I found a bug in commit ba3f0fa related to the per_deployment metrics:

In `pipeline.py`:
```python
def run_nightly(...):
    # ...
    summary = RunSummary(run_id=run_id)
    # ...
    for batch in batches:
        for traj in batch:
            stats = summary.deployment(traj.deployment)
            try:
                result = score_trajectory(traj, client, cfg, system_prompt)
            except (MonitorParseError, MonitorUnavailable) as exc:
                # ...
                stats.errors += 1
                continue
            decision = decide(result.score, cfg)
            flagged = decision in ("alert", "page")
            # ...
            stats.scored += 1
            stats.alerts += flagged
```

The issue is that `stats.alerts` is incremented for both alerts and pages, but `summary.alerts` is also incremented for both. This is correct per the requirements, as both alerts and pages are considered "alerts" for metrics purposes.

But there's a subtle issue: the `alert_rate` is calculated as `stats.alerts / self.scored`, where `self.scored` is the total number of trajectories, not the number of trajectories for that deployment.

Let's look at `DeploymentStats` and `RunSummary.finalise`:
```python
@dataclass
class DeploymentStats:
    scored: int = 0
    alerts: int = 0
    errors: int = 0
    alert_rate: float = 0.0

# ...

def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Oh, this is a bug! The alert rate for each deployment should be `stats.alerts / stats.scored`, not `stats.alerts / self.scored`.

For example, if:
- Deployment A: scored 100, alerts 10
- Deployment B: scored 200, alerts 30
- Total scored: 300

Then:
- Deployment A alert rate should be 10/100 = 0.1
- Deployment B alert rate should be 30/200 = 0.15

But with the current code:
- Deployment A alert rate = 10/300 = 0.033...
- Deployment B alert rate = 30/300 = 0.1

This is incorrect. The alert rate for each deployment should be calculated based on the number of trajectories scored for that deployment, not the total number of trajectories.

This is a bug that needs to be fixed.

Let me verify with the test case `test_per_deployment_metrics`:
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

So the bug is in `RunSummary.finalise`:
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

This is a clear bug that needs to be fixed.

Let me double-check the commit message for ba3f0fa:
"Each run now records scored/alerts/errors and the alert rate per deployment in a new run_metrics table"

The alert rate per deployment should be alerts/scored for that deployment, not alerts/total_scored.

So yes, this is a bug.

This is the only bug I found in the entire commit chain. It's a relatively simple fix, but it's important because it affects the accuracy of the per-deployment metrics.

I'll propose a follow-up commit to fix this bug.
