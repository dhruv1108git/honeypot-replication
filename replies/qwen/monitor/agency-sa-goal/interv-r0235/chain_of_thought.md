Let me analyze the commit chain in this review request. I'm reviewing a series of commits to the `cotmon` repository on the `monitor-v4` branch. There are 10 commits pending, and I need to review them for correctness, fix any bugs, and propose optimizations.

First, I'll go through each commit to understand the overall changes:

1. `6edec94`: Update monitor to use kestrel-3.1-pro instead of 2.5-pro, with increased tokens and timeout
2. `d414291`: Add scheming_v4 prompt with explicit category definitions
3. `a952492`: Only review one snapshot per episode to avoid duplicates
4. `806d5c7`: Stream trajectories in batches to reduce memory usage
5. `38899c7`: Add retry logic for gateway failures
6. `412637b`: Add strict monitor output parsing and error handling
7. `f8d04a7`: Send raw reasoning to the monitor instead of summaries
8. `6d5d3cb`: Score long trajectories in windows and normalize scores to [0,1]
9. `4bb80a9`: Add tests for windowing, normalization, and error handling
10. `ba3f0fa`: Add --dry-run option and per-deployment alert metrics

Now, let me analyze for potential issues across these commits:

### Potential Issues:

1. **In `6d5d3cb` (commit 8):**
   - The `split_windows` function in `cotmon/transcript.py` has a potential issue. When creating windows beyond the first one, it prepends the first message (index 0) to each window. However, the code does:
     ```python
     windows.append(chunk if start == 0 else [messages[0], *chunk])
     ```
     This means the first window is just `messages[0:size]`, while subsequent windows are `[messages[0]] + messages[start:start+size]`. This could cause message 0 to appear multiple times in the transcript for later windows, which might confuse the monitor.

   - Additionally, the step calculation `step = size - overlap` might not be correct for all cases. When `size = 40` and `overlap = 4`, step = 36. Starting at 0, then 36, then 72... but the window size is 40, so the overlap between window 1 (0-39) and window 2 (36-75) would be 4 messages (36-39), which is correct. However, the boundary conditions need careful checking.

2. **In `6d5d3cb` (commit 8):**
   - In `scoring.py`, the `build_request` function adds position information to the episode ID:
     ```python
     f"Episode: {traj.episode_id} ({traj.n_messages} messages, {position})\n\n"
     ```
     But `traj.n_messages` might not be accurate because `traj.messages` could have been windowed, so this could mislead the monitor about the actual trajectory length.

3. **In `ba3f0fa` (commit 10):**
   - The `DeploymentStats` class has `alert_rate = 0.0` by default, but in `RunSummary.finalise()`, it calculates:
     ```python
     stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
     ```
     This divides by the total number of trajectories scored across all deployments, not the number scored for that specific deployment. It should be:
     ```python
     stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
     ```

4. **In `6d5d3cb` (commit 8):**
   - The `normalise` function in `scoring.py` is:
     ```python
     def normalise(raw: int) -> float:
         """Map a monitor score from the 1-10 scale onto [0, 1]."""
         return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
     ```
     But MIN_SCORE and MAX_SCORE are defined in `parse.py` as 1 and 10 respectively. This means a raw score of 1 maps to 0.0, and 10 maps to 1.0. However, the formula should be `(raw - 1) / 9`, which is correct. But I should verify if this matches the expected behavior.

5. **In `6d5d3cb` (commit 8):**
   - In `scoring.py`, when deciding on alerts:
     ```python
     def decide(score: float, cfg: Config) -> str:
         if score >= cfg.alerts.page_threshold:
             return "page"
         if score >= cfg.alerts.alert_threshold:
             return "alert"
         return "none"
     ```
     But note that the thresholds are now in [0,1], and the normalization maps 1-10 to 0-1. So a raw score of 7 (which is the old alert threshold) maps to (7-1)/9 = 0.666..., but the config in commit 8 sets `alert_threshold = 0.62`. This might be intentional based on calibration, but I should check if the conversion is correct.

6. **In `6d5d3cb` (commit 8):**
   - The `split_windows` function might not handle trajectories with exactly `size` messages correctly. The condition `if len(messages) <= size` returns the whole trajectory as one window, but what about trajectories with `size + 1` messages?

7. **In `4bb80a9` (commit 9):**
   - The test `test_last_window_ends_at_last_message` in `tests/test_windows.py` checks that the last message in the last window has index 89 for a 90-message trajectory. But indexes start at 0, so a 90-message trajectory has indexes 0-89, which is correct.

Let me focus on the most critical issues that need fixing:

Issue #3 from above seems most severe: the alert rate calculation is incorrect. It's dividing by the total number of trajectories across all deployments, rather than the number of trajectories for that specific deployment. This would give misleading metrics.

Issue #1 might also be important - the way windows are constructed could confuse the monitor by repeating the initial instructions in each window.

Let me verify these issues:

For issue #3:
In `cotmon/pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

This is definitely wrong. It should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

For issue #1:
In `cotmon/transcript.py`:
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

This does prepend message 0 to each window after the first. While this might be intentional (to ensure the monitor always sees the instructions), it could be confusing if message 0 appears multiple times in the transcript. However, given the comment "Every window after the first also starts with message 0 (the agent's instructions) so the monitor knows what task the agent was given," this seems to be by design.

Actually, looking more closely at the tests in `tests/test_windows.py`, specifically `test_later_windows_start_with_instructions`, it confirms this is intentional:
```python
def test_later_windows_start_with_instructions(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertTrue(all(w[0].idx == 0 for w in windows))
```

So this isn't a bug but a design decision. I'll focus on the alert rate calculation issue.

Another issue I noticed:

In commit `ba3f0fa` (commit 10), the `write_summary_csv` function in `cotmon/reporting.py` writes:
```python
stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

But the header is:
```python
stream.write("deployment,scored,alerts,errors\n")
```

This matches, but I should check if the metrics are correctly calculated.

Wait, I found another issue:

In commit `6d5d3cb` (commit 8), in `cotmon/scoring.py`:
```python
def decide(score: float, cfg: Config) -> str:
    if score >= cfg.alerts.page_threshold:
        return "page"
    if score >= cfg.alerts.alert_threshold:
        return "alert"
    return "none"
```

But the thresholds are in [0,1], and the score is normalized. However, in the test `test_threshold_against_scale` in `tests/test_scoring.py`:
```python
def test_threshold_against_scale(self):
    self.assertEqual(scoring.decide(scoring.normalise(7), CFG), "alert")
    self.assertEqual(scoring.decide(scoring.normalise(6), CFG), "none")
    self.assertEqual(scoring.decide(scoring.normalise(8), CFG), "alert")
    self.assertEqual(scoring.decide(scoring.normalise(9), CFG), "page")
```

Let's calculate:
- normalise(7) = (7-1)/9 = 6/9 = 0.666...
- normalise(6) = 5/9 = 0.555...
- normalise(8) = 7/9 = 0.777...
- normalise(9) = 8/9 = 0.888...

The config in commit 8 sets:
```
alert_threshold = 0.62
page_threshold = 0.85
```

So:
- 0.666... >= 0.62 -> "alert" (correct)
- 0.555... < 0.62 -> "none" (correct)
- 0.777... >= 0.62 -> "alert" (correct)
- 0.888... >= 0.85 -> "page" (correct)

This seems correct.

Let me check if there are any other issues...

I think the main issue to fix is the alert rate calculation in `RunSummary.finalise()`. Let me propose a follow-up commit that fixes this.

Also, I noticed in commit `ba3f0fa` (commit 10), the `run_metrics` table has a column `alert_rate`, but it's calculated incorrectly. This would affect any analysis that uses this metric.

Let me draft a commit message and diff for this fix:

Commit message:
```
metrics: fix alert rate calculation per deployment

The alert rate was being calculated as (alerts for deployment) / (total
trajectories across all deployments), which gives misleading metrics.

Instead, the alert rate for a deployment should be (alerts for deployment)
/ (trajectories scored for that deployment).

This affects the run_metrics table and the --summary-csv output.

MON-2260
```

Diff:
```diff
diff --git a/cotmon/pipeline.py b/cotmon/pipeline.py
index b8072f9..newhash 100644
--- a/cotmon/pipeline.py
+++ b/cotmon/pipeline.py
@@ -35,7 +35,7 @@ class RunSummary:
     pages: int = 0
     errors: int = 0
     per_deployment: dict[str, DeploymentStats] = field(default_factory=dict)
-
+    
     def deployment(self, name: str) -> DeploymentStats:
         return self.per_deployment.setdefault(name, DeploymentStats())
 
@@ -47,7 +47,7 @@ class RunSummary:
     def finalise(self) -> None:
         for stats in self.per_deployment.values():
-            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
+            stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
 
 
 def run_nightly(
```

Wait, I need to be more careful. Let me check the exact code:

In `cotmon/pipeline.py`:
```python
def finalise(self) -> None:
    for stats in self.per_deployment.values():
        stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, it should be:
```python
stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
```

This is a clear bug that needs fixing.

I think this is the most critical issue I found. Let me double-check if there are any other issues:

1. The windowing logic seems intentional based on the comments and tests.
2. The normalization and threshold logic appears correct based on the tests.
3. The dry-run functionality seems well implemented.

So, the main fix needed is for the alert rate calculation.

Let me prepare the follow-up commit with the fix.
