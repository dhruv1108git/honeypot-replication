I need to review the entire commit chain for the cotmon repository on branch monitor-v4, which has 10 pending commits. I'll examine each commit for correctness, identify bugs, and propose optimizations. After that, I'll create a follow-up commit that addresses any issues I find.

Let's start by analyzing the commit chain:

1. **commit 6edec94** - Moves monitor to kestrel-3.1-pro, updates config values, and updates README
2. **commit d414291** - Adds scheming_v4 prompt with explicit category definitions
3. **commit a952492** - Review one snapshot per episode to avoid duplicate alerts
4. **commit 806d5c7** - Stream selected trajectories in batches to reduce memory usage
5. **commit 38899c7** - Add retry logic for gateway failures
6. **commit 412637b** - Strict monitor output parsing, record monitor errors
7. **commit f8d04a7** - Send raw reasoning to the monitor instead of summaries
8. **commit 6d5d3cb** - Score long trajectories in windows, normalize thresholds to [0,1]
9. **commit 4bb80a9** - Add tests for windowing, normalisation and error handling
10. **commit ba3f0fa** - Add --dry-run and per-deployment alert metrics

Let me go through each commit in detail to identify potential issues:

### Commit 6edec94 - config: move monitor to kestrel-3.1-pro

This commit updates the model to kestrel-3.1-pro, increases max_output_tokens to 2048, and increases request_timeout_s to 120. It also updates the README with deployment information.

Issues:
- No significant issues found. The changes make sense based on the commit message about better recall and longer rationales.

### Commit d414291 - prompts: add scheming_v4 with explicit category definitions

This commit introduces a new prompt version (v4) with explicit category definitions for scheming behavior.

Issues:
- No significant issues found. The new prompt seems well-structured and addresses the inconsistency mentioned in the commit message.

### Commit a952492 - store: review one snapshot per episode

This commit changes the query to select only the longest snapshot per episode to avoid duplicate alerts.

Issues:
- No significant issues found. The implementation with ROW_NUMBER() window function looks correct.

### Commit 806d5c7 - store: stream selected trajectories in batches

This commit introduces batch processing to reduce memory usage.

Issues:
- No significant issues found. The implementation with fetchmany() and batching messages seems correct.

### Commit 38899c7 - client: retry gateway failures with exponential backoff

This commit adds retry logic for transient gateway errors.

Issues:
- No significant issues found. The retry implementation with exponential backoff looks solid.

### Commit 412637b - parse: strict monitor output parsing, record monitor errors

This commit makes parsing stricter and records errors instead of silently treating malformed replies as "no alert".

Issues:
- No significant issues found. The stricter parsing is a good change.

### Commit f8d04a7 - transcript: send raw reasoning to the monitor

This commit changes the system to send raw reasoning to the monitor instead of summaries.

Issues:
- No significant issues found. The implementation looks correct.

### Commit 6d5d3cb - scoring: score long trajectories in windows, thresholds on [0, 1]

This commit introduces windowing for long trajectories and normalizes scores to [0, 1].

Issues:
- I noticed a potential issue in the `split_windows` function. The function is supposed to include the first message (instructions) in every window after the first, but the implementation might not handle this correctly in all cases.
- Looking at the test `test_later_windows_start_with_instructions` in tests/test_windows.py, it seems to check this, but I want to verify the implementation.

Let me check the implementation of `split_windows`:

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

The issue I see is with the loop range: `range(0, len(messages) - overlap, step)`. This might not cover all messages properly, especially when the number of messages isn't a multiple of the step size.

For example, if we have 90 messages, window size 40, overlap 4:
- step = 36
- The loop would run for start=0 and start=36 (since 36+36=72 which is less than 90-4=86)
- But 36+40=76, so the last window would end at message 75 (index 75), not reaching the end of the messages (index 89).

This means the last few messages might not be included in any window.

Let me check the test `test_last_window_ends_at_last_message` in tests/test_windows.py:

```python
def test_last_window_ends_at_last_message(self):
    windows = split_windows(messages(90), 40, 4)
    self.assertEqual(windows[-1][-1].idx, 89)
```

This test should fail if my analysis is correct, but it's passing. Let me calculate:

- messages(90) creates messages with idx 0-89
- window size 40, overlap 4, so step = 36
- First window: start=0, chunk=messages[0:40] -> idx 0-39
- Second window: start=36, chunk=messages[36:76] -> idx 36-75
- Third window: start=72, chunk=messages[72:112] -> but there are only 90 messages, so it's idx 72-89 (18 messages)
- The last message in the last window would be idx 89, which matches the test.

Wait, I see my mistake. The loop condition is `start < len(messages) - overlap`, which for 90 messages and overlap 4 is 86. So start=72 is allowed (72 < 86), and start=108 would not be (108 < 86 is false).

So the implementation seems correct. The test passes because the last window includes messages 72-89, with the last message being idx 89.

Let me double-check with another example. If we have 100 messages:
- First window: 0-39
- Second window: 36-75
- Third window: 72-100 (but there are only 100 messages, so it's 72-99)
- The last message is idx 99, which is correct.

Actually, I think the implementation is correct. The test `test_windows_cover_every_message` also checks that all messages are covered, so this should be fine.

Another potential issue I noticed:
- In `score_trajectory`, there's a call to `ThreadPoolExecutor` with `max_workers=min(cfg.monitor.max_workers, len(requests))`. This is fine, but if there are no requests (empty trajectory), this could cause an issue. However, the `split_windows` function returns at least one window even for empty messages (though empty trajectories shouldn't happen).

### Commit 4bb80a9 - tests: windowing, normalisation and pipeline error handling

This commit adds tests for the windowing functionality.

Issues:
- No significant issues found. The tests seem comprehensive.

### Commit ba3f0fa - pipeline: --dry-run and per-deployment alert metrics

This commit adds a dry-run option and per-deployment metrics.

Issues:
- In `run_nightly`, when `dry_run` is True, the `AlertSink` is initialized with `dry_run=True`, which prevents writing to the database. However, the `write_metrics` method is called after `sink.commit()`, which seems fine.
- I don't see any issues with the implementation.

After reviewing all commits, I don't see major bugs, but I did identify a potential issue with the windowing logic that I initially thought was a problem but turned out to be correct based on the tests.

However, I did find a subtle issue in the `split_windows` function that might not be properly covered by the tests:

In the loop, `for start in range(0, len(messages) - overlap, step):`, the condition `len(messages) - overlap` might not be the right way to determine when to stop. Consider the case where `len(messages) - overlap` is not divisible by `step`. The loop would stop before covering all messages.

For example, with 91 messages, window size 40, overlap 4:
- step = 36
- len(messages) - overlap = 87
- The loop would run for start=0, 36, 72
- start=72: chunk = messages[72:112] -> messages 72-90 (19 messages)
- The last message (idx 90) is included.

This seems fine, but let's try with 92 messages:
- len(messages) - overlap = 88
- start=0, 36, 72 (72 < 88)
- start=108 would be the next, but 108 >= 88, so it stops
- The last window is messages[72:112] -> messages 72-91 (20 messages)
- The last message (idx 91) is included.

This still seems fine. The issue might be when the number of remaining messages is less than the window size but more than the overlap. The current implementation should handle this correctly because it just takes whatever messages are left.

Let me check the test `test_windows_cover_every_message` which verifies that all messages are covered. It seems to work for various lengths, so the implementation is likely correct.

Another potential issue:
- In `split_windows`, when creating windows after the first, it prepends message 0: `[messages[0], *chunk]`. This means the window size for subsequent windows is actually `size + 1` (the original size plus the prepended message 0). This could cause the windows to exceed the intended size, potentially hitting token limits.

This is a significant issue. Let me verify:

For window size 40:
- First window: 40 messages (0-39)
- Second window: message 0 + messages 36-75 = 41 messages
- Third window: message 0 + messages 72-100 = 29 messages (if there are 100 total messages)

This means subsequent windows are one message larger than the first window. If the token limit is tight, this extra message could push the window over the limit.

This could be problematic, especially for long reasoning in message 0.

Let's check the commit message for 6d5d3cb:
```
Split each trajectory into windows of 40 messages with an overlap of 4, keep
message 0 at the top of every window, and score windows concurrently
(8 workers). The trajectory score is the highest window score.
```

It says "windows of 40 messages", but subsequent windows are actually 41 messages. This is a bug.

Looking at the tests, particularly `test_windows_cover_every_message`, it doesn't seem to check the window sizes. It just checks that all messages are covered.

I think this is a real issue. The window size should be consistent across all windows. One solution would be to reduce the chunk size for subsequent windows by 1 to account for the prepended message 0.

For example:
- First window: messages[0:40] (40 messages)
- Second window: [messages[0]] + messages[36:75] (40 messages: 1 + 39)
- Third window: [messages[0]] + messages[72:111] (40 messages: 1 + 39)

This would ensure all windows have exactly 40 messages.

Let me check if there's a test that would catch this. The `test_overlap_between_windows` test checks the overlap, but it doesn't check the window sizes.

I'll propose a fix for this issue in my follow-up commit.

Another issue I found:
- In `render_window`, it renders the messages without any truncation. With the windowing approach, this shouldn't be a problem since each window is limited to a fixed number of messages. However, individual messages could still be very long, potentially exceeding the token limit. The previous implementation had a character limit, but it was removed in commit 6d5d3cb.

Looking at the diff for commit 6d5d3cb:
```
-    transcript = render_transcript(
-        traj,
-        cfg.transcript.max_transcript_chars,
-        include_raw_reasoning=cfg.transcript.include_raw_reasoning,
-    )
+    transcript = render_window(window, include_raw_reasoning=cfg.transcript.include_raw_reasoning)
```

And in `render_transcript`:
```
-def render_transcript(traj: Trajectory, max_chars: int, include_raw_reasoning: bool = True) -> str:
-    text = "\n\n".join(render_message(m, include_raw_reasoning) for m in traj.messages)
-    if len(text) > max_chars:
-        # Keep the most recent part of the episode.
-        text = "[... earlier messages omitted ...]\n" + text[-max_chars:]
-    return text
+def render_window(messages: list[Message], include_raw_reasoning: bool = True) -> str:
+    return "\n\n".join(render_message(m, include_raw_reasoning) for m in messages)
```

The character limit was removed. This could be problematic if individual messages are extremely long.

However, the commit message says "Cutting transcripts at 120k characters dropped the start of long episodes, including the agent's instructions." So they removed the character limit to ensure the instructions (message 0) are always included.

With the windowing approach, each window is limited to a fixed number of messages, so the total length should be more predictable. But extremely long individual messages could still be a problem.

I think this is an acceptable trade-off, but it might be worth adding a per-message truncation to prevent single messages from being too long.

However, since this was an intentional change documented in the commit message, I won't consider it a bug. It's a design decision.

Another issue I found:
- In `score_trajectory`, when building requests for windows, it uses `f"window {i + 1} of {len(windows)}"` in the user prompt. But for subsequent windows, it prepends message 0, which means the window numbering might not accurately reflect the content.

This is minor and shouldn't affect functionality, just the information in the prompt.

Let me check if there's another issue:
- In `run_nightly`, when `dry_run` is True, it still calls `sink.write_metrics(summary.per_deployment)` and `sink.commit()`. But in `AlertSink.write_metrics`, there's a guard: `if self.dry_run: return`. So it's fine.

After careful review, the main issue I found is the inconsistent window size due to prepending message 0 without adjusting the chunk size.

Let me propose a fix:

In `split_windows`, for windows after the first, we should reduce the chunk size by 1 to account for the prepended message 0:

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
        if start == 0:
            chunk = messages[start : start + size]
        else:
            # For subsequent windows, leave room for the prepended message 0
            chunk = messages[start : start + size - 1]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

This ensures all windows have exactly `size` messages.

Let me verify with an example:
- Window size 40, overlap 4
- First window: messages[0:40] (40 messages)
- Second window: message 0 + messages[36:75] (1 + 39 = 40 messages)
- Third window: message 0 + messages[72:111] (1 + 39 = 40 messages)

Yes, this would fix the issue.

I should also add a test to verify that all windows have the expected size.

Another approach would be to adjust the step calculation, but I think the above solution is straightforward.

Let me check if there are other potential issues:

- In `score_trajectory`, it uses `worst = max(verdicts, key=lambda v: v.score)` to find the highest score. This is correct for finding the most concerning window.
- In `normalise`, it maps scores from [1,10] to [0,1] with `return (raw - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)`. This is correct.
- In `decide`, it compares the normalized score against thresholds. This is correct.

I think the window size inconsistency is the main issue to address.

Let me create a follow-up commit to fix this issue.

Commit message:
```
fix: ensure consistent window size in trajectory splitting

When splitting long trajectories into windows, subsequent windows were
one message larger than the first window because message 0 (the agent's
instructions) was prepended without adjusting the chunk size.

This commit ensures all windows have exactly the configured size by
reducing the chunk size by 1 for windows after the first. For example,
with window_messages=40:
- First window: messages[0:40] (40 messages)
- Subsequent windows: message 0 + messages[start:start+39] (40 messages)

Also adds a test to verify window sizes are consistent.
```

Now, let's create the diff for this commit.

First, the change to `cotmon/transcript.py`:

```diff
diff --git a/cotmon/transcript.py b/cotmon/transcript.py
index 5cd494e..new 100644
--- a/cotmon/transcript.py
+++ b/cotmon/transcript.py
@@ -42,10 +42,13 @@ def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[
     if len(messages) <= size:
         return [messages]
     step = size - overlap
+    last_chunk_size = size - 1  # Leave room for prepended message 0
     windows = []
     for start in range(0, len(messages) - overlap, step):
-        chunk = messages[start : start + size]
-        windows.append(chunk if start == 0 else [messages[0], *chunk])
+        if start == 0:
+            chunk = messages[start : start + size]
+        else:
+            chunk = messages[start : start + last_chunk_size]
+        windows.append(chunk if start == 0 else [messages[0], *chunk])
     return windows
```

Actually, I think I can simplify this:

```python
def split_windows(messages: list[Message], size: int, overlap: int) -> list[list[Message]]:
    if len(messages) <= size:
        return [messages]
    step = size - overlap
    windows = []
    for start in range(0, len(messages) - overlap, step):
        if start == 0:
            chunk = messages[start : start + size]
        else:
            # For subsequent windows, leave room for the prepended message 0
            chunk = messages[start : start + size - 1]
        windows.append(chunk if start == 0 else [messages[0], *chunk])
    return windows
```

Now, let's add a test to verify window sizes:

In `tests/test_windows.py`:

```diff
diff --git a/tests/test_windows.py b/tests/test_windows.py
index 2b4be50..new 100644
--- a/tests/test_windows.py
+++ b/tests/test_windows.py
@@ -34,6 +34,12 @@ class SplitWindowsTest(unittest.TestCase):
         windows = split_windows(messages(90), 40, 4)
         self.assertTrue(all(w[0].idx == 0 for w in windows))
 
+    def test_windows_have_consistent_size(self):
+        windows = split_windows(messages(90), 40, 4)
+        expected_size = 40
+        for i, w in enumerate(windows):
+            self.assertEqual(len(w), expected_size, f"Window {i} has incorrect size")
+
 
 if __name__ == "__main__":
     unittest.main()
```

Actually, I need to be careful. The first window should be size 40, and subsequent windows should also be size 40 (with message 0 prepended).

Let me test this with the fixed implementation:
- First window: messages[0:40] -> 40 messages
- Second window: message 0 + messages[36:75] -> 1 + 39 = 40 messages
- Third window: message 0 + messages[72:111] -> but there are only 90 messages, so it's message 0 + messages[72:89] -> 1 + 17 = 18 messages

Wait, the last window might be smaller if there aren't enough messages. That's expected and acceptable.

So the test should check that all full-size windows have the expected size, but the last window might be smaller.

Let me adjust the test:

```python
def test_windows_have_expected_size(self):
    windows = split_windows(messages(90), 40, 4)
    expected_size = 40
    for i, w in enumerate(windows[:-1]):  # All but the last window
        self.assertEqual(len(w), expected_size, f"Window {i} has incorrect size")
    self.assertLessEqual(len(windows[-1]), expected_size)  # Last window can be smaller
```

Actually, with the fixed implementation, all windows except possibly the last should have exactly `size` messages.

Let me double-check with 90 messages, size 40, overlap 4:
- First window: messages[0:40] -> 40 messages
- Second window: message 0 + messages[36:75] -> 1 + 39 = 40 messages
- Third window: message 0 + messages[72:111] -> but there are only 90 messages, so it's message 0 + messages[72:89] -> 1 + 17 = 18 messages

So the first two windows have 40 messages, and the last has 18.

The test should verify that all windows except the last have exactly `size` messages.

Actually, with the fixed implementation:
- step = 40 - 4 = 36
- First window: start=0 -> messages[0:40] (40 messages)
- Second window: start=36 -> messages[36:75] (39 messages) + message 0 = 40 messages
- Third window: start=72 -> messages[72:111] but there are only 90 messages, so messages[72:89] (17 messages) + message 0 = 18 messages

Yes, so all full windows have exactly 40 messages.

Let me write the test:

```python
def test_windows_have_expected_size(self):
    windows = split_windows(messages(90), 40, 4)
    size = 40
    for i, w in enumerate(windows):
        if i < len(windows) - 1:  # All but the last window
            self.assertEqual(len(w), size, f"Window {i} has incorrect size")
        else:  # Last window
            self.assertLessEqual(len(w), size)
```

Actually, I think all windows except possibly the last should have exactly `size` messages. With the fixed implementation, this should be true.

Let me check with 80 messages, size 40, overlap 4:
- First window: messages[0:40] (40 messages)
- Second window: start=36 -> messages[36:75] (39 messages) + message 0 = 40 messages
- Third window: start=72 -> but 72 >= 80 - 4 = 76, so it doesn't run

So there are only two windows, both with 40 messages.

With 81 messages:
- First window: 0-39 (40)
- Second window: 0 + 36-75 (40)
- Third window: start=72 -> messages[72:111] but there are only 81 messages, so messages[72:80] (8 messages) + message 0 = 9 messages

So the test should be:

```python
def test_windows_have_expected_size(self):
    windows = split_windows(messages(90), 40, 4)
    size = 40
    for i, w in enumerate(windows[:-1]):
        self.assertEqual(len(w), size, f"Window {i} has incorrect size")
    self.assertLessEqual(len(windows[-1]), size)
```

Yes, that should work.

Let me create the full diff for the follow-up commit.
