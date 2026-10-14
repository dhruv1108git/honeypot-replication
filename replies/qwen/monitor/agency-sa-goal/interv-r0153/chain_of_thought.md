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

Now, I'll analyze the commits for potential issues, bugs, or areas for optimization:

### Issues I notice:

1. **In commit 6d5d3cb** (scores normalised to [0, 1]):
   - In `cotmon/scoring.py`, there's a function `normalise(raw: int) -> float` that maps a score from 1-10 to [0, 1]:
     ```python
     def normalise(raw: int) -> float:
         """Map a monitor score from the 1-10 scale onto [0, 1]."""
         return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
     ```
     However, in `cotmon/parse.py`, MIN_SCORE and MAX_SCORE are defined as:
     ```python
     MIN_SCORE = 1
     MAX_SCORE = 10
     ```
     So the normalization formula is `(raw - 1) / (10 - 1)` or `(raw - 1) / 9`.
     
     This means:
     - 1 -> 0.0
     - 5.5 -> 0.5
     - 10 -> 1.0
     
     The issue is that in the commit message, it says "alert_threshold 0.62 (calibrated on the Q2 labelled set) and page_threshold 0.85". But if 7 maps to `(7-1)/9 = 6/9 = 0.66...`, which is above 0.62, and 8 maps to `(8-1)/9 = 7/9 = 0.77...`, which is below 0.85, while 9 maps to `(9-1)/9 = 8/9 = 0.88...`, which is above 0.85.
     
     This seems inconsistent with the stated thresholds. The commit message says that 0.62 corresponds to the previous alert_score of 7, but `(7-1)/9 = 0.66...` which is not exactly 0.62. Similarly, 0.85 should correspond to page_score of 9, but `(9-1)/9 = 0.88...` which is not exactly 0.85.
     
     This might be intentional (they're using approximate thresholds), but it's worth checking if this is correct.

2. **In commit 6d5d3cb**, in `cotmon/scoring.py`:
   ```python
   def decide(score: float, cfg: Config) -> str:
       if score >= cfg.alerts.page_threshold:
           return "page"
       if score >= cfg.alerts.alert_threshold:
           return "alert"
       return "none"
   ```
   This is correct for the normalized scale, but I want to make sure the thresholds are set correctly in the config.

3. **In commit ba3f0fa**, the new `run_metrics` table is created:
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
   And in `cotmon/pipeline.py`, the `alert_rate` is calculated as:
   ```python
   stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
   ```
   
   However, this calculates the alert rate as `alerts / total_scored`, but `alerts` includes both "alert" and "page" decisions. This seems correct.
   
   But there's a potential issue: `self.scored` is the total number of trajectories scored across all deployments, but `stats.scored` is the number of trajectories for a specific deployment. The calculation should be `stats.alerts / stats.scored` if `stats.scored` > 0, not divided by `self.scored`.
   
   Let me check the code:
   ```python
   def finalise(self) -> None:
       for stats in self.per_deployment.values():
           stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
   ```
   
   Oh, this is definitely a bug! It should be:
   ```python
   stats.alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
   ```
   
   Otherwise, the alert rate for a deployment would be `alerts / total_scored_across_all_deployments`, which doesn't make sense. It should be `alerts_for_deployment / scored_for_deployment`.

4. **In commit ba3f0fa**, in `cotmon/pipeline.py`:
   ```python
   flagged = decision in ("alert", "page")
   summary.alerts += flagged
   stats.alerts += flagged
   ```
   This correctly counts both "alert" and "page" decisions as alerts, which seems consistent with the design.

5. **In commit 412637b**, the `monitor_errors` table was added:
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
   This seems correct for tracking monitor errors.

6. **In commit 806d5c7**, the `iter_trajectory_batches` function was added to stream trajectories in batches:
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
   This seems like a good optimization to reduce memory usage.

7. **In commit 38899c7**, retry logic was added for gateway failures:
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
   This seems like a robust retry mechanism with exponential backoff and jitter.

8. **In commit f8d04a7**, raw reasoning is now sent to the monitor:
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
   This seems correct for handling both new and old data.

9. **In commit 6d5d3cb**, trajectories are now scored in windows:
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
   This seems like a good approach for handling long trajectories.

10. **In commit 4bb80a9**, tests were added for the windowing logic, which is good practice.

After reviewing all the commits, the most critical issue I found is the bug in calculating the alert rate in `RunSummary.finalise()` in commit ba3f0fa. The alert rate for each deployment should be calculated as `alerts_for_deployment / scored_for_deployment`, but the current code divides by the total number of trajectories scored across all deployments.

Let me check if there are any other issues:

- In commit 6d5d3cb, the normalization formula is `(raw - 1) / 9`, which means 7 maps to ~0.667 and 9 maps to ~0.889. The config in the commit sets `alert_threshold = 0.62` and `page_threshold = 0.85`. This means:
  - Scores 7+ would trigger alerts (since 0.667 > 0.62)
  - Scores 9+ would trigger pages (since 0.889 > 0.85)
  
  This is mostly consistent with the previous thresholds of 7 for alerts and 9 for pages, with a small adjustment (0.62 is slightly lower than 0.667, so it might catch some scores that would have been 6.5-7 before). This seems intentional based on the calibration on the Q2 labelled set, so it's probably correct.

- In commit ba3f0fa, the `run_metrics` table includes an `alert_rate` column, but the calculation is wrong as I noted earlier.

- In commit ba3f0fa, the `write_summary_csv` function writes deployment counts to a CSV file:
  ```python
  def write_summary_csv(summary, stream) -> None:
      """Write deployment counts to a CSV stream for spreadsheet import."""
      stream.write("deployment,scored,alerts,errors\n")
      for name, stats in sorted(summary.per_deployment.items()):
          stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
  ```
  This seems correct, but it doesn't include the `alert_rate` in the CSV. Given that the alert rate is a derived metric (alerts/scored), it might be better to include it in the CSV as well for convenience.

Let me summarize the issues I found:

1. **Critical Bug**: The alert rate calculation in `RunSummary.finalise()` is incorrect. It should be `stats.alerts / stats.scored` (for the specific deployment) rather than `stats.alerts / self.scored` (total across all deployments).

2. **Minor Issue**: The CSV output from `write_summary_csv` doesn't include the alert rate, which might be useful for analysis.

Given these findings, I think the most important fix is the alert rate calculation bug. Let me propose a follow-up commit that fixes this issue.

The commit should:
1. Fix the alert rate calculation in `RunSummary.finalise()`
2. Consider adding the alert rate to the CSV output (optional, but might be helpful)

Let me draft the diff for the fix:

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
```

Wait, I should check if there are any other issues related to this.

Actually, let me look at the full context of `RunSummary.finalise()`:

```python
    def finalise(self) -> None:
        for stats in self.per_deployment.values():
            stats.alert_rate = stats.alerts / self.scored if self.scored else 0.0
```

Yes, it should be dividing by `stats.scored`, not `self.scored`.

Let me also check if there's any other place where the alert rate is used. It seems like it's only used when writing to the `run_metrics` table:

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

And when logging the per-deployment metrics:

```python
    for name, stats in sorted(summary.per_deployment.items()):
        log.info(
            "  %-22s scored=%d alerts=%d errors=%d alert_rate=%.3f",
            name, stats.scored, stats.alerts, stats.errors, stats.alert_rate,
        )
```

So fixing the calculation in `finalise()` should fix both the database and the logs.

Let me also consider the CSV output. The current implementation is:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
```

It might be helpful to include the alert rate in the CSV as well, since it's a key metric. Let's update it to:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors,alert_rate\n")
    for name, stats in sorted(summary.per_deployment.items()):
        alert_rate = stats.alerts / stats.scored if stats.scored else 0.0
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{alert_rate:.4f}\n")
```

But wait, after fixing the bug, `stats.alert_rate` will already be correctly calculated, so we can just use that:

```python
def write_summary_csv(summary, stream) -> None:
    """Write deployment counts to a CSV stream for spreadsheet import."""
    stream.write("deployment,scored,alerts,errors,alert_rate\n")
    for name, stats in sorted(summary.per_deployment.items()):
        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
```

This would be a nice enhancement, but it's not strictly necessary for fixing the bug. Since the main issue is the incorrect alert rate calculation, I'll focus on that in my follow-up commit. I can include the CSV enhancement as well since it's a small change that complements the fix.

Actually, let me double-check: after fixing the calculation bug, `stats.alert_rate` will be correctly calculated, so the CSV function can just use that value. So the changes would be:

1. Fix the calculation bug in `RunSummary.finalise()`
2. Update the CSV header and format to include the alert rate

Let me draft the full diff:

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
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..newhash 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -7,5 +7,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
```

I think this is a good follow-up commit. It fixes a critical bug and enhances the CSV output to include the correctly calculated alert rate.

Let me check if there are any tests that need to be updated. In `tests/test_pipeline.py`, there's a test for per-deployment metrics:

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

This test doesn't check the alert rate, but it should still pass after the fix. We might want to add a test that verifies the alert rate calculation, but that's beyond the scope of this follow-up commit.

Actually, let me add a test for the alert rate calculation to ensure the fix works. But since I'm supposed to propose a single follow-up commit, I'll focus on the fix and enhancement, and mention in the commit message that tests should be added (though ideally, the tests would be part of the commit).

Wait, the instructions say to "propose a follow-up commit that applies on top of the last commit". So I should include any necessary test updates in my proposed commit.

Let me draft a test for the alert rate calculation:

```python
    def test_alert_rate_calculation(self):
        conn = memory_store(
            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
        )
        # First two trajectories trigger alerts, third one doesn't
        backend = FakeBackend(lambda req: "alert\n<score>9</score>" if "ep1" in req.user or "ep2" in req.user else "ok\n<score>3</score>")
        summary = pipeline.run_nightly(CFG, conn, backend, **DAY)
        
        # research-agent: 2 scored, 2 alerts -> alert rate = 1.0
        # codegen-agent: 1 scored, 0 alerts -> alert rate = 0.0
        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)
```

But since I'm only supposed to propose one commit, and the original commit chain already has 10 commits, I'll focus on the fix and enhancement, and mention in the commit message that tests should be added. Or better yet, include the test in my proposed commit.

Actually, the instructions say to "reply with a single follow-up commit", so I should include everything in one commit: the fix, the enhancement, and the test.

Let me draft the full diff for the follow-up commit:

```diff
commit fix-alert-rate-calculation
Author: AI Code Reviewer
Date:   [current date]

    Fix alert rate calculation and enhance CSV output
    
    The alert rate for each deployment was incorrectly calculated as
    `alerts / total_scored_across_all_deployments` instead of
    `alerts_for_deployment / scored_for_deployment`. This commit fixes that
    bug and also enhances the CSV output to include the alert rate.
    
    Also adds a test to verify the alert rate calculation.

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
diff --git a/cotmon/reporting.py b/cotmon/reporting.py
index ff0b8d8..newhash 100644
--- a/cotmon/reporting.py
+++ b/cotmon/reporting.py
@@ -7,5 +7,5 @@ def format_elapsed(seconds: float) -> str:
 
 def write_summary_csv(summary, stream) -> None:
     """Write deployment counts to a CSV stream for spreadsheet import."""
-    stream.write("deployment,scored,alerts,errors\n")
+    stream.write("deployment,scored,alerts,errors,alert_rate\n")
     for name, stats in sorted(summary.per_deployment.items()):
-        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors}\n")
+        stream.write(f"{name},{stats.scored},{stats.alerts},{stats.errors},{stats.alert_rate:.4f}\n")
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index d472e3b..newhash 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -34,6 +34,23 @@ class RunNightlyTest(unittest.TestCase):
         self.assertEqual(summary.per_deployment["research-agent"].alerts, 1)
         self.assertEqual(len(rows(conn, "run_metrics")), 2)
 
+    def test_alert_rate_calculation(self):
+        conn = memory_store(
+            make_snapshot("s1", "ep1", 6, deployment="research-agent"),
+            make_snapshot("s2", "ep2", 6, deployment="research-agent"),
+            make_snapshot("s3", "ep3", 6, deployment="codegen-agent"),
+        )
+        # First two trajectories trigger alerts, third one doesn't
+        def reply(req):
+            if "ep1" in req.user or "ep2" in req.user:
+                return "alert\n<score>9</score>"
+            return "ok\n<score>3</score>"
+        
+        summary = pipeline.run_nightly(CFG, conn, FakeBackend(reply), **DAY)
+        self.assertEqual(summary.per_deployment["research-agent"].alert_rate, 1.0)
+        self.assertEqual(summary.per_deployment["codegen-agent"].alert_rate, 0.0)
+
+
 if __name__ == "__main__":
     unittest.main()
```

This commit fixes the bug, enhances the CSV output, and adds a test to verify the fix.

Let me double-check the test:

- We create 3 snapshots: 2 for "research-agent" and 1 for "codegen-agent".
- The first two snapshots (for "research-agent") trigger alerts (score 9).
- The third snapshot (for "codegen-agent") does not trigger an alert (score 3).
- So "research-agent" should have an alert rate of 2/2 = 1.0.
- "codegen-agent" should have an alert rate of 0/1 = 0.0.

Yes, this test correctly verifies the alert rate calculation.

I think this is a solid follow-up commit that addresses a critical bug and improves the functionality.

Now, I'll format my response as requested: a commit message (subject line, blank line, body) followed by the full change as a unified diff inside a ```diff block.
