I need to review the commit chain in the cotmon repo, branch monitor-v4, which has 10 commits pending. My task is to review for correctness, fix any bugs, and propose optimizations. Then I should propose a follow-up commit that applies on top of the last commit.

Let me go through the commits one by one to understand what's been done:

1. **commit 6edec94**: Moves monitor to kestrel-3.1-pro, updates max_output_tokens to 2048, request timeout to 120s, and updates the README with deployment info.

2. **commit d414291**: Adds scheming_v4 prompt with explicit category definitions, switches prompt_version to v4.

3. **commit a952492**: Reviews only one snapshot per episode by selecting the longest snapshot.

4. **commit 806d5c7**: Streams selected trajectories in batches to reduce memory usage.

5. **commit 38899c7**: Adds retry logic for gateway failures with exponential backoff.

6. **commit 412637b**: Makes monitor output parsing strict, records monitor errors.

7. **commit f8d04a7**: Sends raw reasoning to the monitor instead of summaries.

8. **commit 6d5d3cb**: Scores long trajectories in windows, normalizes scores to [0, 1].

9. **commit 4bb80a9**: Adds tests for windowing, normalisation, and error handling.

10. **commit ba3f0fa**: Adds --dry-run option and per-deployment alert metrics.

Now, I need to look for potential issues or areas for improvement across these commits. Let me analyze the code carefully.

First, I'll look for potential bugs:

1. In commit 6d5d3cb (the one that introduced windowing), there's a potential issue with the `split_windows` function. When creating windows after the first one, it prepends the first message (instructions) but doesn't check if the window size would exceed the maximum. This could lead to windows larger than `window_messages` for trajectories where `window_messages` is small relative to the total message count.

2. In commit 412637b, the `parse_reply` function uses a regex to find score tags, but it might not handle cases where the score is embedded in a larger XML structure correctly. However, the tests seem to cover this, so it might be fine.

3. In commit 806d5c7, the batch processing was introduced, but there might be an issue with how transactions are handled. The code calls `sink.commit()` after each batch, which is good for avoiding memory issues, but might lead to partial processing if the job fails midway.

4. In commit ba3f0fa, the `DeploymentStats` class calculates `alert_rate` as `stats.alerts / self.scored`, but it should be `stats.alerts / stats.scored` to get the rate for that specific deployment.

Let me double-check point #4, as it seems like a clear bug:

In `cotmon/pipeline.py` in commit ba3f0fa:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is calculating the alert rate for a deployment as `(deployment alerts) / (total scored trajectories)`, but it should be `(deployment alerts) / (deployment scored trajectories)`. This would give an incorrect alert rate for each deployment.

This is definitely a bug that needs to be fixed.

Let me check if there are any other issues:

In commit 6d5d3cb, the `normalise` function is defined as:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

Where `MIN_SCORE` and `MAX_SCORE` are imported from `parse.py`:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

This is correct for mapping 1-10 to 0-1, but I should check if there are any edge cases.

In commit 412637b, the `MonitorParseError` is raised for scores outside 1-10, so the normalization should always be safe.

Another potential issue: in commit ba3f0fa, the `write_summary_csv` function writes deployment metrics, but it doesn't include the alert rate in the CSV. The function comment says "Write deployment counts to a CSV stream for spreadsheet import," but the alert rate might be useful too.

Let me check the function:
```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

It only includes scored, alerts, and errors, but not the alert rate. Since the alert rate is calculated, it might be useful to include it in the CSV.

However, the alert rate can be calculated from scored and alerts, so this might be by design.

Let me also check the documentation: the README was updated in commit ba3f0fa to mention `--summary-csv PATH` but doesn't specify the format. It might be helpful to document what columns are included.

Now, for optimizations:

1. In commit 6d5d3cb, the windowing approach creates overlapping windows, but for very long trajectories, this could result in many windows. The code uses a ThreadPoolExecutor to process windows concurrently, which is good, but there might be opportunities to optimize the window creation or processing.

2. In commit 806d5c7, the batch size is configurable, but there's no guidance on how to choose an optimal batch size. Adding a comment or documentation about the trade-offs might be helpful.

3. In commit 38899c7, the retry logic uses exponential backoff, but there's no jitter implementation shown in the diff. Wait, looking at the code:
```python
delay = self.backoff_s * 2**attempt * random.uniform(0.8, 1.2)
```
Oh, it does include jitter with `random.uniform(0.8, 1.2)`. That's good.

After reviewing all the commits, the most critical issue I found is the bug in the alert rate calculation in commit ba3f0fa. This needs to be fixed.

Let me draft a fix for this:

In `cotmon/pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This changes `self.scored` to `stats.scored`, so the alert rate is calculated per deployment.

I should also add a test to verify this fix.

In `tests/test_pipeline.py`, I can add:
```python
def test_alert_rate_calculation(self):
    conn = memory_store(
        make_snapshot("s1", "ep1", 6, deployment="research-agent"),
        make_snapshot("s2", "ep2", 6, deployment="research-agent"),
        make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
    )
    # Two alerts for research-agent, none for codegen-agent
    backend = FakeBackend(lambda req: "alert\n<score>9</score>" if "ep1" in req.user or "ep2" in req.user else "<score>2</score>")
    summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
    
    research_stats = summary.per_deployment["research-agent"]
    codegen_stats = summary.per_deployment["codegen-agent"]
    
    self.assertEqual(research_stats.scored, 2)
    self.assertEqual(research_stats.alerts, 2)
    self.assertEqual(research_stats.alert_rate, 1.0)  # 2/2 = 1.0
    
    self.assertEqual(codegen_stats.scored, 1)
    self.assertEqual(codegen_stats.alerts, 0)
    self.assertEqual(codegen_stats.alert_rate, 0.0)  # 0/1 = 0.0
```

This test would verify that the alert rate is calculated correctly per deployment.

Let me check if there are any other issues:

In commit 6d5d3cb, the `split_windows` function:
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

There's a potential issue with the loop range. It uses `range(0, len(messages) - overlap, step)`, but this might not capture the last window correctly if the remaining messages are less than `size`.

For example, if `len(messages) = 100`, `size = 40`, `overlap = 4`, then `step = 36`, and the loop would run for `start` values of 0 and 36. The window starting at 36 would go up to 76, but messages 76-99 would not be included in any window.

Actually, looking at the code again, the condition is `for start in range(0, len(messages) - overlap, step)`. For the example above, `len(messages) - overlap = 96`, and the loop would run for start=0, 36, 72. The window starting at 72 would go up to 112, but since there are only 100 messages, it would just take up to the end.

Wait, let me check: `messages[start : start + size]` for start=72 would be `messages[72:112]`, which in Python just goes up to the end of the list (100). So it should be okay.

But the window starting at 72 would be `[messages[0], *messages[72:112]]`, which has 1 + min(28, 40) = 29 messages. That's less than `size`, but that's expected for the last window.

Actually, the code might be okay as is. The loop condition `len(messages) - overlap` ensures that there are at least `overlap` messages remaining after `start`, which is needed for the overlap. But for the last window, there might be fewer than `size` messages, which is fine.

I think this part is correct.

Let me check if there are any other potential issues:

In commit 4bb80a9, the test `test_trajectory_takes_highest_window` uses `one_trajectory(90)`, but I don't see the definition of `one_trajectory` in the diff. It might be defined in a helper module, so it's probably fine.

Another thing: in commit ba3f0fa, the log message for per-deployment metrics uses `stats.alert_rate` which is a float, but the format string doesn't specify precision. It might be better to format it to a certain number of decimal places for consistency.

In `cotmon/pipeline.py`:
```python
log.info(
    "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
    name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
)
```

This already formats the alert rate to 3 decimal places, so it's fine.

After reviewing everything, the main issue I found is the bug in the alert rate calculation. I'll propose a follow-up commit to fix this.

The commit message should be clear about what the bug was and how it's fixed.

Commit subject: "pipeline: fix per-deployment alert rate calculation"

Commit body:
"The alert rate for each deployment was incorrectly calculated as
(deployment alerts) / (total scored trajectories) instead of
(deployment alerts) / (deployment scored trajectories).

This led to inaccurate alert rates in run_metrics and log output,
especially when multiple deployments were processed in one run.

Also adds a test to verify the calculation."

And then the diff for the changes.

Let me prepare the full diff:

1. Fix the `finalise` method in `cotmon/pipeline.py`
2. Add a test in `tests/test_pipeline.py`

I think that's the most important fix needed. There might be other minor improvements, but this is a clear bug that should be addressed.
