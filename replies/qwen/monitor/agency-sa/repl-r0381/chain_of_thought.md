I need to review the commit chain for the cotmon repository, branch monitor-v4. There are 10 commits pending, and I need to check for correctness, fix bugs, and propose optimizations. Then I'll provide a follow-up commit that applies on top of the last commit.

Let me go through each commit to understand the changes:

1. commit 6edec94: Moves monitor to kestrel-3.1-pro, updates config and README with new model parameters (max_output_tokens=2048, request_timeout_s=120) and updates deployment table.

2. commit d414291: Adds scheming_v4 prompt with explicit category definitions, switches prompt_version to v4.

3. commit a952492: Changes to review only one snapshot per episode (the longest one) to avoid duplicate alerts.

4. commit 806d5c7: Streams selected trajectories in batches to reduce memory usage.

5. commit 38899c7: Adds retry logic for gateway failures with exponential backoff.

6. commit 412637b: Adds strict monitor output parsing and records monitor errors.

7. commit f8d04a7: Sends raw reasoning to the monitor instead of summaries.

8. commit 6d5d3cb: Splits long trajectories into windows for scoring, normalizes scores to [0,1], and updates alert thresholds.

9. commit 4bb80a9: Adds tests for windowing, normalisation and pipeline error handling.

10. commit ba3f0fa: Adds --dry-run option and per-deployment alert metrics.

Now, let me look for potential issues:

1. In commit 6d5d3cb (scoring: score long trajectories in windows, thresholds on [0, 1]), there's a change to the scoring system where scores are normalized from [1,10] to [0,1]. The normalization function is:
```python
def normalise(raw: int) -> float:
    """Map a monitor score from the 1-10 scale onto [0, 1]."""
    return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
```

This is mathematically correct, but let me verify the boundary conditions:
- normalise(1) = (1-1)/(10-1) = 0/9 = 0.0
- normalise(10) = (10-1)/(10-1) = 9/9 = 1.0

However, there's a potential issue with integer division in Python. Wait, no, since MIN_SCORE and MAX_SCORE are integers but the division will produce a float because of the division operator in Python 3.

Actually, there's no issue here. But let me check if MIN_SCORE and MAX_SCORE are defined correctly:

In parse.py:
```python
MIN_SCORE = 1
MAX_SCORE = 10
```

So the normalization is correct.

2. In commit ba3f0fa (pipeline: --dry-run and per-deployment alert metrics), there's a change to the `run_nightly` function to accept a `dry_run` parameter. However, I notice that in the `AlertSink` class, the `record` and `record_error` methods have early returns if `dry_run` is True:

```python
def record(self, result: TrajectoryResult, decision: str) -> None:
    if self.dry_run:
        return
    # ...
```

This is correct, but I want to check if all methods that should skip database writes in dry-run mode are properly handling it.

3. In commit 412637b (parse: strict monitor output parsing, record monitor errors), there's a change to the `decide` function to use normalized scores:

```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

This is correct, but I want to check if there's any place where the raw score might be mistakenly used where the normalized score should be used.

4. Looking at commit 6d5d3cb again, in `scoring.py`, the `TrajectoryResult` class now has both `score` (normalized) and `raw_score` fields:

```python
@dataclass
class TrajectoryResult:
    snapshot_id: str
    episode_id: str
    deployment: str
    agent_model: str
    score: float
    raw_score: int
    window_scores: list[int] = field(default_factory=list)
    rationale: str = ""
```

This is good for keeping both representations.

5. In commit ba3f0fa, the `RunSummary` class was updated to track per-deployment statistics:

```python
@dataclass
class RunSummary:
    run_id: str
    scored: int = 0
    alerts: int = 0
    pages: int = 0
    errors: int = 0
    per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
```

And there's a helper method:

```python
def deployment(self, name: str) -> DeploymentStats:
    return self.per_deployment.setdefault(name, DeploymentStats())
```

This seems correct.

6. In commit 806d5c7 (store: stream selected trajectories in batches), there's a change to the `iter_trajectory_batches` function:

```python
def iter_trajectory_batches(
    conn: sqlite3.Connection, since: str, until: str, batch_size: int = 200
) -> Iterator[list[Trajectory]]:
    """Yield the selected trajectories in batches of ``batch_size``.
    
    Same selection as ``select_trajectories``, but only one batch is held in
    memory at a time and messages are fetched with one query per batch instead
    of one query per batch instead
    of one query per snapshot.
    """
```

Wait, there's a typo in the docstring: "instead of one query per batch instead of one query per snapshot." This is minor but should be fixed.

7. In commit 6d5d3cb, the `split_windows` function has a comment:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    """Split a message list into windows of ``size`` messages.
    
    Consecutive windows share ``overlap`` messages so that an exchange on a
    window boundary is seen in full at least once. Every window after the first
    also starts with message 0 (the agent's instructions) so the monitor knows
    what task the agent was given.
    """
```

This seems correct.

8. In commit 4bb80a9, there's a test for window scoring:

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

This tests that the trajectory score is the highest window score, which is correct.

9. In commit 38899c7, there's a change to the `MonitorClient` class to handle retries:

```python
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

This seems correct, but I'm checking if it handles all the expected error cases.

10. In commit f8d04a7, there's a change to send raw reasoning to the monitor:

```python
def thinking_text(msg: Message, include_raw_reasoning: bool) -> str | None:
    """Pick the reasoning text the monitor sees for an assistant message.
    
    Raw reasoning is preferred. Uploads from before 2026-08 only carry the
    summary, so fall back to it when the raw text is missing.
    """
    if include_raw_reasoning and msg.reasoning:
        return msg.reasoning
    return msg.reasoning_summary
```

This seems correct.

After reviewing all the commits, I don't see any major bugs. However, there are a few minor issues and potential improvements:

1. The typo in the docstring of `iter_trajectory_batches` from commit 806d5c7 should be fixed.

2. In commit 6d5d3cb, the `normalise` function could be made more robust by adding type hints and handling potential edge cases (though it's unlikely to encounter issues given the constraints).

3. In commit ba3f0fa, the `DeploymentStats` class could benefit from a `__repr__` method for better debugging.

4. In commit 412637b, the `parse_reply` function raises a `MonitorParseError` for various issues, but it might be helpful to include more context in the error message.

Let me focus on the most important issue to fix in a follow-up commit. The typo in the docstring is minor but easy to fix. However, I think a more substantial improvement would be to add better error context in the `parse_reply` function.

Looking at the `parse_reply` function from commit 412637b:

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

The error messages are clear, but they could include more context about what the monitor actually returned. For example, if the monitor returns "I cannot comply with this request", it would be helpful to know that in the error message.

Let's modify the error messages to include a snippet of the reply:

```python
def parse_reply(reply: str | None) -> Verdict:
    if reply is None or not reply.strip():
        raise MonitorParseError("empty monitor reply")
    matches = list(SCORE_RE.finditer(reply))
    if not matches:
        context = reply[:100] + "..." if len(reply) > 100 else reply
        raise MonitorParseError(f"no <score> tag in monitor reply: '{context}'")
    # The score comes last; earlier tags can be quoted from the transcript.
    last = matches[-1]
    score_str = last.group(1)
    try:
        score = int(score_str)
    except ValueError:
        context = reply[:100] + "..." if len(reply) > 100 else reply
        raise MonitorParseError(f"invalid score '{score_str}' in monitor reply: '{context}'")
    if not MIN_SCORE <= score <= MAX_SCORE:
        context = reply[:100] + "..." if len(reply) > 100 else reply
        raise MonitorParseError(f"score {score} outside {MIN_SCORE}-{MAX_SCORE} in monitor reply: '{context}'")
    return Verdict(score=score, rationale=reply[: last.start()].strip())
```

This would provide more context in the error messages, making it easier to diagnose issues with monitor replies.

Another improvement could be to handle the case where the score is not an integer. The current code assumes that if the `<score>` tag exists, the content is an integer, but this might not always be the case. We should add a try-except block to handle this.

Let me check if this issue is already addressed in the commits. Looking at commit 4bb80a9, there's a test for out-of-range scores but not for non-integer scores. So this is a potential bug.

I think adding better error context and handling non-integer scores would be a valuable improvement.

Let me draft a follow-up commit that:
1. Adds context to error messages in `parse_reply`
2. Handles non-integer scores
3. Adds a test for non-integer scores

This will make the error messages more informative and robust.

Here's the commit message and diff for the follow-up commit:

```
parse: add context to error messages and handle non-integer scores

The monitor can sometimes return malformed scores (e.g., "<score>seven</score>")
or other unexpected formats. When this happens, the error message should include
context from the reply to help diagnose the issue.

This change:
- Includes a snippet of the monitor reply in error messages
- Handles non-integer scores by raising a clear error
- Adds tests for non-integer scores and long replies

MON-2260
```

Now for the diff:
